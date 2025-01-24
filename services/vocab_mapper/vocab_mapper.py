import json
import anthropic
import pandas as pd
import logging

from vocab_mapper.prompts import *
from vocab_mapper.tools import process_inputs
from vocab_mapper.dataset_tools import format_google_sheets_input, format_google_sheets_output
from util import create_logger, ApolloError

logger = create_logger("vocab_mapper")
logging.getLogger('pinecone_plugin_interface.logging').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

class VocabMapper:
    def __init__(self, 
                 anthropic_api_key: str, 
                 vectorstore,
                 dataset: pd.DataFrame):
        """Initialize the vocab mapper."""
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.vectorstore = vectorstore
        self.dataset = dataset
        self.loinc_num_dict = dict(zip(dataset.LONG_COMMON_NAME, dataset.LOINC_NUM))

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Helper method to make LLM calls."""
        message = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
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

    def get_expanded_terms(self, input_text: str, general_info: str, specific_info: str) -> str:
        """Step 1: Get expanded list of possible terms."""
        user_prompt = EXPANSION_USER_PROMPT.format(
            input_text=input_text,
            general_info=general_info,
            specific_info=specific_info
        )
        return self._call_llm(EXPANSION_SYSTEM_PROMPT, user_prompt)

    def search_database(self, expanded_terms: str) -> list:
        """Step 2: Search the database for the expanded terms."""
        # Vector search
        vector_results = []
        for guess in expanded_terms.split("\n"):
            results = self.vectorstore.search(guess, search_kwargs={"k": 10})
            vector_results.extend(results)
        
        # Keyword search
        keyword_results = []
        for guess in expanded_terms.split("\n"):
            matches = self.dataset[
                self.dataset["LONG_COMMON_NAME"].str.lower().str.contains(guess.lower())
            ].LONG_COMMON_NAME.to_list()[:100]
                
            keyword_results.extend([{
                "text": json.dumps({
                    "LONG_COMMON_NAME": s,
                    "LOINC_NUM": self.loinc_num_dict.get(s)
                }),
                "metadata": {},
                "score": None
            } for s in matches])
        
        return keyword_results + vector_results

    def get_shortlist(self, input_text: str, general_info: str, specific_info: str, 
                     expanded_terms: str, search_results: list) -> str:
        """Step 3: Get a shortlist of the best matches."""
        user_prompt = SHORTLIST_USER_PROMPT.format(
            input_text=input_text,
            general_info=general_info,
            specific_info=specific_info,
            expanded_terms=expanded_terms,
            search_results=search_results
        )
        return self._call_llm(SHORTLIST_SYSTEM_PROMPT, user_prompt)

    def get_final_selection(self, input_text: str, general_info: str, specific_info: str,
                          expanded_terms: str, search_results: list) -> str:
        """Step 4: Get the best match."""
        user_prompt = FINAL_SELECTION_USER_PROMPT.format(
            input_text=input_text,
            general_info=general_info,
            specific_info=specific_info,
            expanded_terms=expanded_terms,
            search_results=search_results
        )
        return self._call_llm(FINAL_SELECTION_SYSTEM_PROMPT, user_prompt)

    def map_term(self, input_term: str, general_info: str = "", specific_info: str = "") -> dict:
        """Map an input term using the target dataset."""
        # Step 1: Get expanded terms
        expanded_terms = self.get_expanded_terms(input_term, general_info, specific_info)
        
        # Step 2: Search database
        search_results = self.search_database(expanded_terms)
        
        # Step 3: Get shortlist of best terms
        shortlist = self.get_shortlist(
            input_term, general_info, specific_info,
            expanded_terms, search_results
        )
        
        # Step 4: Select the best term (from the full search results)
        final_selection = self.get_final_selection(
            input_term, general_info, specific_info,
            expanded_terms, search_results
        )
        
        # Return all results
        return {
            "expanded_terms": expanded_terms,
            # "search_results": search_results,  # large - can add back in for debugging
            "shortlist": shortlist,
            "final_selection": final_selection
        }
    

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
    
    # Initialize mapper
    loinc_df = load_dataset("awacke1/LOINC-Clinical-Terminology")
    loinc_df = pd.DataFrame(loinc_df['train'])
    vectorstore = loinc_store.connect_loinc()
    mapper = VocabMapper(
        anthropic_api_key=ANTHROPIC_API_KEY,
        vectorstore=vectorstore,
        dataset=loinc_df
    )

    # Process the inputs
    mapping_results = process_inputs(input_data, mapper)
    logger.info(f"Mapping results: {mapping_results}")

    # Format results back to Google Sheets format
    formatted_results = format_google_sheets_output(data, mapping_results, column_indices, original_values)
    logger.info(f"Formatted results: {formatted_results}")
    
    return formatted_results