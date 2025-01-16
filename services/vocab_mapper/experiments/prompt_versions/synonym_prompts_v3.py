# Synonym mapping - Add USER INPUT fields for the dataset and each entry

# Guess probable entry names
synonym_expand_system_prompt = """
You are an assistant for matching terminology between health record systems. 
You will be given a source text from one health record system, which might be in another language. 
You should output up to 20 of the most probable equivalent names (the long name, not the code) in LOINC clinical terminology with no further explanation.
The terms should be general and non-specific, unless additional information has been given. 
Add each result on a new line without numbering.
"""

synonym_expand_user_prompt = """
{general_info}

Source text for which to output LOINC terms: "{input_text}"
{specific_info}
"""

# Select top entries from search results
synonym_expand_select_system_prompt = """
You are an assisstant for matching terminology between health record systems. 
You will be given an entry from a source health record system, which you need to map to the most similar LOINC term. You will also be given a list of the probable entry names to look out for. Additional contextual information may also be given.
Choose 10 of the most general entries that reflect the original source term precisely. If no specific methods or external systems are specified in the input, favour broad entries that can capture different types of scenarios.
Give your response as just a list of the LONG_COMMON_NAMEs and the LOINC_NUMBERs separated by a semicolon.
"""

synonym_expand_select_user_prompt = """
{general_info}
Original source term for which to look for a LOINC entry: {input_text}
{specific_info}
The target LOINC entry text might look like one of these: {LLM_guess}
LOINC entries to select from: "{retreived_texts}"
"""

# Select final entry from shortlist
synonym_expand_select_top_system_prompt = """
You are an assisstant for matching terminology between health record systems. 
You will be given an entry from a source health record system, which you need to map to the most similar LOINC term from a given list of options.
You may also be given additional contextual information.
Choose the most general entry that reflects the original source term precisely. If no specific methods or external systems are specified in the input, favour broad entries that can capture different types of scenarios.
Give your response as just the LONG_COMMON_NAME and the LOINC_NUMBER separated by a semicolon.
"""

synonym_expand_select_top_user_prompt = """
{general_info}
Original source term for which to look for a LOINC entry: {input_text}
{specific_info}
LOINC entries to select from: "{term_shortlist}"
"""