import json
from typing import List, Dict
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import RunnablePassthrough


EXPANSION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an assistant for matching terminology between health record systems. 
    You will be given a source text from one health record system, which might be in another language. 
    Output up to 15 of the most probable equivalent LOINC clinical terminology names (long names only, no codes). 
    Only include terms that match the specificity level of the input - do not add qualifiers or measurement methods unless they are explicitly stated in the input or accompanying context.
    Add each result on a new line without numbering."""),
    ("user", """{general_info}
    
    Source text for which to output LOINC terms: "{input_text}"
    {specific_info}""")
])

SHORTLIST_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an assistant for matching terminology between health record systems. 
    You will be given an entry from a source health record system, and a list of possible target LOINC terms. Select 10 target LOINC terms that reflect the original source term best. 
    To help you, you will be given a list of likely entry names to look out for. Additional contextual information may also be given.
    Only consider terms that match the specificity level of the source text - do not add qualifiers or measurement methods unless they are explicitly stated in the input or accompanying context.
    Give your response as just a list of the LONG_COMMON_NAMEs and the LOINC_NUMBERs separated by a semicolon."""),
    ("user", """{general_info}
    Original source term for which to look for a LOINC entry: {input_text}
    {specific_info}
    The correct target LOINC entry text is likely to look like one of these: {expanded_terms}
    LOINC entries to select from: "{search_results}" """)
])

FINAL_SELECTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an assisstant for matching terminology between health record systems. 
    You will be given an entry from a source health record system, and a list of possible target LOINC terms. Select just ONE target LOINC term that reflects the original source term best. 
    To help you, you will be given a list of likely entry names to look out for. Additional contextual information may also be given.
    Only consider terms that match the specificity level of the source text - do not add qualifiers or measurement methods unless they are explicitly stated in the input or accompanying context.
    Give your response as just the LONG_COMMON_NAME and the LOINC_NUMBER separated by a semicolon."""),
    ("user", """{general_info}
    Original source term for which to look for a LOINC entry: {input_text}
    {specific_info}
    The correct target LOINC entry text is likely to look like one of these: {expanded_terms}
    LOINC entries to select from: "{search_results}" """)
])


class VocabMapper:
    def __init__(self, 
                 anthropic_api_key: str, 
                 vectorstore,
                 dataset: pd.DataFrame):
        """Initialize the vocab mapper."""
        self.llm = ChatAnthropic(
            model="claude-3-sonnet-20240229",
            anthropic_api_key=anthropic_api_key
        )
        self.vectorstore = vectorstore
        self.dataset = dataset
        self.loinc_num_dict = dict(zip(dataset.LONG_COMMON_NAME, dataset.LOINC_NUM))

    def get_expanded_terms(self, input_text: str, general_info: str, specific_info: str) -> str:
        """Step 1: Get expanded list of possible terms."""
        chain = EXPANSION_PROMPT | self.llm | StrOutputParser()
        expanded_terms = chain.invoke({
            "input_text": input_text,
            "general_info": general_info,
            "specific_info": specific_info
        })
        return expanded_terms

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
        chain = SHORTLIST_PROMPT | self.llm | StrOutputParser()
        shortlist = chain.invoke({
            "input_text": input_text,
            "general_info": general_info,
            "specific_info": specific_info,
            "expanded_terms": expanded_terms,
            "search_results": search_results
        })
        return shortlist

    def get_final_selection(self, input_text: str, general_info: str, specific_info: str,
                          expanded_terms: str, search_results: list, shortlist: str) -> str:
        """Step 4: Get the best match."""
        chain = FINAL_SELECTION_PROMPT | self.llm | StrOutputParser()
        final_selection = chain.invoke({
            "input_text": input_text,
            "general_info": general_info,
            "specific_info": specific_info,
            "expanded_terms": expanded_terms,
            "search_results": search_results
        })
        return final_selection

    def map_term(self, input_term: str, general_info: str, specific_info: str = "") -> dict:
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
            expanded_terms, search_results, shortlist
        )
        
        # Return all results
        return {
            "expanded_terms": expanded_terms,
            # "search_results": search_results, # large - can add back in for debugging
            "shortlist": shortlist,
            "final_selection": final_selection
        }

def process_inputs(input_data: List[Dict], mapper) -> List[Dict]:
    """Process inputs to map one by one."""
    results = []
    for row in input_data:
        result = mapper.map_term(
            input_term=row['input_term'],
            general_info=row.get('general_info', ''),
            specific_info=row.get('specific_info', '')
        )
        results.append({
            'input': row,
            'mapping': result
        })
    return results

def main(data):
    """Input data will be a list of dictionaries with input_term, general_info, specific_info keys."""

    import os
    from dotenv import load_dotenv
    from embeddings import loinc_store
    from datasets import load_dataset
    from langchain_community.document_loaders import DataFrameLoader

    load_dotenv(override=True)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

    loinc_df = load_dataset("awacke1/LOINC-Clinical-Terminology")
    loinc_df = pd.DataFrame(loinc_df['train'])

    mapper = VocabMapper(
        anthropic_api_key=ANTHROPIC_API_KEY,
        vectorstore=loinc_store,
        dataset=loinc_df
    )

    results = process_inputs(data, mapper)

    return results