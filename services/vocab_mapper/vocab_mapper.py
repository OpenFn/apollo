import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

import anthropic
import pandas as pd

from vocab_mapper.prompts import *
from vocab_mapper.dataset_tools import format_google_sheets_input, format_google_sheets_output
from util import create_logger, ApolloError

logger = create_logger("vocab_mapper")
logging.getLogger('pinecone_plugin_interface.logging').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

class VocabMapper:
    def __init__(self, 
                 anthropic_api_key: str, 
                 vectorstore,
                 dataset: pd.DataFrame,
                 batch_size: int = 30,
                 max_concurrent_calls: int = 25):
        """Initialize the vocab mapper."""
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.vectorstore = vectorstore
        self.dataset = dataset
        self.loinc_num_dict = dict(zip(dataset.LONG_COMMON_NAME, dataset.LOINC_NUM))
        self.batch_size = batch_size
        self.max_concurrent_calls = max_concurrent_calls
    
    def _batch_iterator(self, items, batch_size):
        for i in range(0, len(items), batch_size):
            yield items[i:i + batch_size]

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Helper method to make LLM calls."""
        message = self.client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=500,
            temperature=0,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
                        }
                    ]
                }
            ]
        )
        return message.content[0].text

    def _call_llm_batch(self, system_prompt: str, user_prompts: List[str]) -> List[str]:
        """Process a batch of LLM inputs concurrently."""
        with ThreadPoolExecutor(max_workers=self.max_concurrent_calls) as executor:
            futures = [
                executor.submit(self._call_llm, system_prompt, prompt)
                for prompt in user_prompts
            ]
            return [future.result() for future in futures]
   
    def _get_expanded_terms(self, inputs: List[Dict[str, str]]) -> List[str]:
        """Process a batch of inputs for term expansion."""
        user_prompts = [
            EXPANSION_USER_PROMPT.format(
                input_text=input_data["input_term"],
                general_info=input_data.get("general_info", ""),
                specific_info=input_data.get("specific_info", "")
            )
            for input_data in inputs
        ]
        return self._call_llm_batch(EXPANSION_SYSTEM_PROMPT, user_prompts)

    def _search_database(self, expanded_terms: str) -> list:
        """Search the database for expanded terms."""

        def process_term(guess):
            results = []
            # Vector search
            vector_results = self.vectorstore.search(guess, search_kwargs={"k": 10})
            results.extend(vector_results)

            return results

        # Process all terms from a single input's expanded_terms in parallel
        terms = expanded_terms.split("\n")
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(process_term, terms))

        return [item for sublist in results for item in sublist]
    
    def _search_database_batch(self, expanded_terms_list: List[str]) -> List[list]:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self._search_database, expanded_terms)
                for expanded_terms in expanded_terms_list
            ]
            return [future.result() for future in futures]

    def _keyword_search(self, expanded_terms: str) -> list:
        """Search the dataset with a keyword-based search."""

        def process_term(guess):
            results = []
            
            # Keyword search
            matches = self.dataset[
                self.dataset["LONG_COMMON_NAME_LOWER"].str.contains(guess.lower())
            ].LONG_COMMON_NAME.to_list()[:100]
            
            results.extend([{
                "text": json.dumps({
                    "LONG_COMMON_NAME": s,
                    "LOINC_NUM": self.loinc_num_dict.get(s)
                }),
                "metadata": {},
                "score": None
            } for s in matches])
            return results

        # Process all terms from a single input's expanded_terms in parallel
        terms = expanded_terms.split("\n")
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(process_term, terms))

        return [item for sublist in results for item in sublist]

    def _get_shortlist(self, inputs: List[Dict], expanded_terms_list: List[str], 
                          search_results_list: List[list]) -> List[str]:
        """Process a batch of inputs for shortlisting."""
        user_prompts = [
            SHORTLIST_USER_PROMPT.format(
                input_text=input_data["input_term"],
                general_info=input_data.get("general_info", ""),
                specific_info=input_data.get("specific_info", ""),
                expanded_terms=expanded_terms,
                search_results=search_results
            )
            for input_data, expanded_terms, search_results 
            in zip(inputs, expanded_terms_list, search_results_list)
        ]
        return self._call_llm_batch(SHORTLIST_SYSTEM_PROMPT, user_prompts)
    
    def _get_final_selection(self, inputs: List[Dict], expanded_terms_list: List[str],
                                search_results_list: List[list]) -> List[str]:
        """Process a batch of inputs for final selection."""
        user_prompts = [
            FINAL_SELECTION_USER_PROMPT.format(
                input_text=input_data["input_term"],
                general_info=input_data.get("general_info", ""),
                specific_info=input_data.get("specific_info", ""),
                expanded_terms=expanded_terms,
                search_results=search_results
            )
            for input_data, expanded_terms, search_results 
            in zip(inputs, expanded_terms_list, search_results_list)
        ]
        return self._call_llm_batch(FINAL_SELECTION_SYSTEM_PROMPT, user_prompts)

    def _map_terms_batch(self, inputs: List[Dict]) -> List[Dict]:
        """Map a batch of input terms using the target dataset."""
        # Step 1: Get expanded terms for the batch
        logger.info(f"Generating search terms based on inputs")
        expanded_terms_list = self._get_expanded_terms(inputs)

        # Step 2: Search database for all expanded terms
        logger.info(f"Searching vector database")
        database_results_list = self._search_database_batch(expanded_terms_list)
        logger.info(f"Searching by keywords")
        keyword_results_list = [self._keyword_search(expanded_terms) for expanded_terms in expanded_terms_list]
        search_results_list = [vec + key for vec, key in zip(keyword_results_list, database_results_list)]

        # Step 3: Get shortlists of best terms for the batch
        logger.info(f"Generating a shortlist of best target terms")
        shortlist_list = self._get_shortlist(
            inputs, expanded_terms_list, search_results_list
        )

        # Step 4: Select the best terms for the batch
        logger.info(f"Generating the best target term")
        final_selection_list = self._get_final_selection(
            inputs, expanded_terms_list, search_results_list
        )

        # Return all results
        return [
            {
                "expanded_terms": expanded_terms,
                "shortlist": shortlist,
                "final_selection": final_selection
            }
            for expanded_terms, shortlist, final_selection 
            in zip(expanded_terms_list, shortlist_list, final_selection_list)
        ]
    
    def _preprocess_dataset(self):
        """Preprocess dataset to keep only necessary columns and add lowercased names for search."""
        # Keep only needed columns
        self.dataset = self.dataset[['LONG_COMMON_NAME', 'LOINC_NUM']]
        # Add lowercase column
        self.dataset['LONG_COMMON_NAME_LOWER'] = self.dataset.LONG_COMMON_NAME.str.lower()

    def map_terms(self, input_data):
        """Process a list of inputs in batches."""
        logger.info(f"Preprocessing dataset")
        self._preprocess_dataset()

        logger.info(f"Starting mapping")
        results = []
        for batch in self._batch_iterator(input_data, self.batch_size):
            batch_results = self._map_terms_batch(batch)
            results.extend([
                {
                    'input': input_row,
                    'mapping': mapping
                }
                for input_row, mapping in zip(batch, batch_results)
            ])
        logger.info(f"Finished mapping")
        return results


def main(data):
    """Map vocab with the VocabMapper using Google Sheets input data. Format output for Google Sheets."""
    import os
    from dotenv import load_dotenv
    from embeddings import loinc_store
    from datasets import load_dataset
    
    logger.info(f"Input data: {data}")

    # Format Google Sheets data
    input_data, column_indices, original_values = format_google_sheets_input(data)
    logger.info(f"Formatted input data: {input_data}")

    load_dotenv(override=True)
    ANTHROPIC_API_KEY = data.get('anthropicApiKey') or os.environ.get('ANTHROPIC_API_KEY')
    OPENAI_API_KEY = data.get('openaiApiKey') or os.environ.get('OPENAI_API_KEY')
    PINECONE_API_KEY = data.get('pineconeApiKey') or os.environ.get('PINECONE_API_KEY')

    # Check for missing keys
    missing_keys = []
    if not ANTHROPIC_API_KEY:
        missing_keys.append("ANTHROPIC_API_KEY")
    if not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY") 
    if not PINECONE_API_KEY:
        missing_keys.append("PINECONE_API_KEY")

    if missing_keys:
        msg = f"Missing API keys: {', '.join(missing_keys)}"
        logger.error(msg)
        raise ApolloError(500, f"Missing API keys: {', '.join(missing_keys)}", type="BAD_REQUEST")
    
    # Get dataset
    logger.info(f"Getting the dataset")
    os.makedirs("tmp", exist_ok=True)

    if os.path.exists("tmp/loinc_dataset.csv"):
        loinc_df = pd.read_csv("tmp/loinc_dataset.csv")
    else:
        loinc_df = pd.DataFrame(load_dataset("awacke1/LOINC-Clinical-Terminology")['train'])
        loinc_df.to_csv("tmp/loinc_dataset.csv", index=False)

    vectorstore = loinc_store.connect_loinc()

    # Initialize mapper
    mapper = VocabMapper(
        anthropic_api_key=ANTHROPIC_API_KEY,
        vectorstore=vectorstore,
        dataset=loinc_df,
        batch_size=25,
        max_concurrent_calls=2
    )

    # Process the inputs
    mapping_results = mapper.map_terms(input_data)
    logger.info(f"Mapping results: {mapping_results}")

    # Format results back to Google Sheets format
    formatted_results = format_google_sheets_output(data, mapping_results, column_indices, original_values)
    logger.info(f"Formatted results: {formatted_results}")
    
    return formatted_results