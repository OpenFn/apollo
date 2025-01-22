EXPANSION_SYSTEM_PROMPT = """You are an assistant for matching terminology between health record systems. 
You will be given a source text from one health record system, which might be in another language. 
Output up to 15 of the most probable equivalent LOINC clinical terminology names (long names only, no codes). 
Only include terms that match the specificity level of the input - do not add qualifiers or measurement methods unless they are explicitly stated in the input or accompanying context.
Add each result on a new line without numbering."""

EXPANSION_USER_PROMPT = """{general_info}

Source text for which to output LOINC terms: "{input_text}"
{specific_info}"""

SHORTLIST_SYSTEM_PROMPT = """You are an assistant for matching terminology between health record systems. 
You will be given an entry from a source health record system, and a list of possible target LOINC terms. Select 10 target LOINC terms that reflect the original source term best. 
To help you, you will be given a list of likely entry names to look out for. Additional contextual information may also be given.
Only consider terms that match the specificity level of the source text - do not add qualifiers or measurement methods unless they are explicitly stated in the input or accompanying context.
Give your response as just a list of the LONG_COMMON_NAMEs and the LOINC_NUMBERs separated by a semicolon."""

SHORTLIST_USER_PROMPT = """{general_info}
Original source term for which to look for a LOINC entry: {input_text}
{specific_info}
The correct target LOINC entry text is likely to look like one of these: {expanded_terms}
LOINC entries to select from: "{search_results}" """

FINAL_SELECTION_SYSTEM_PROMPT = """You are an assistant for matching terminology between health record systems. 
You will be given an entry from a source health record system, and a list of possible target LOINC terms. Select just ONE target LOINC term that reflects the original source term best. 
To help you, you will be given a list of likely entry names to look out for. Additional contextual information may also be given.
Only consider terms that match the specificity level of the source text - do not add qualifiers or measurement methods unless they are explicitly stated in the input or accompanying context.
Give your response as just the LONG_COMMON_NAME and the LOINC_NUMBER separated by a semicolon."""

FINAL_SELECTION_USER_PROMPT = """{general_info}
Original source term for which to look for a LOINC entry: {input_text}
{specific_info}
The correct target LOINC entry text is likely to look like one of these: {expanded_terms}
LOINC entries to select from: "{search_results}" """