import json
import re
from typing import Dict, List, Any, Optional

def filter_adaptor_docs(docs_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses raw OpenFn adaptor documentation JSON and filters it into a clean,
    structured format suitable for use in an AI prompt.

    The function extracts key information for public-facing functions and types,
    including their descriptions, parameters, and examples. It removes internal
    or private symbols and trims unnecessary boilerplate.

    Args:
        docs_json: The raw documentation JSON object from a describe_package call.

    Returns:
        A dictionary containing two lists: 'functions' and 'types', with
        filtered and structured documentation.
    """
    

    jsdoc_pattern = re.compile(
        r'/\*\*(.*?)\*/\s*export (?:declare )?(?:function|type|const|interface)\s*(\w+).*?(?:;|{)',
        re.DOTALL
    )


    filtered_docs = {
        "functions": [],
        "types": []
    }

    for package_name, package_data in docs_json.items():
        doc_string = package_data.get("description", "")
        
        matches = jsdoc_pattern.findall(doc_string)
        
        for jsdoc_content, symbol_name in matches:

            is_public = "@public" in jsdoc_content
            is_private = "@private" in jsdoc_content
            
            if not is_public and is_private:
                continue

            description_match = re.match(r'[\s\S]*?(?=@)', jsdoc_content)
            description = (
                description_match.group(0).strip()
                .replace("*", "").replace("/", "").strip()
                .replace("\n ", "\n")  
            )


            params = []
            param_matches = re.findall(r"@param\s+{(.*?)}\s*(\w+)\s*-\s*(.*)", jsdoc_content)
            for param_type, param_name, param_desc in param_matches:
                params.append({
                    "name": param_name,
                    "type": param_type,
                    "description": param_desc.strip()
                })


            examples = []

            example_matches = re.findall(r"@example(?:.*?)\n([\s\S]+?)(?=\n\s*\*\s*@|\n\s*\*/)", jsdoc_content)
            for example_content in example_matches:
                clean_example = re.sub(r'^\s*\* ?', '', example_content, flags=re.MULTILINE).strip()
                examples.append(clean_example)
            
            if "function" in jsdoc_content:
                filtered_docs["functions"].append({
                    "name": symbol_name,
                    "description": description,
                    "params": params,
                    "examples": examples
                })
            elif "type" in jsdoc_content or "@typedef" in jsdoc_content:
                properties = []
                prop_matches = re.findall(r"@property\s+{(.*?)}\s*(\w+)\s*-\s*(.*)", jsdoc_content)
                for prop_type, prop_name, prop_desc in prop_matches:
                    properties.append({
                        "name": prop_name,
                        "type": prop_type,
                        "description": prop_desc.strip()
                    })

                filtered_docs["types"].append({
                    "name": symbol_name,
                    "description": description,
                    "properties": properties,
                    "examples": examples
                })

    return filtered_docs


try:
    with open("apollo/services/describe_adaptor_py/cache/@openfn_language-http_7.2.0.json", 'r') as file:
        docs_json = json.load(file)
    json_string = json.dumps(docs_json)
    print(f"Total JSON as string: {len(json_string)} characters")
    
    filtered_output = filter_adaptor_docs(docs_json)


    final = json.dumps(filtered_output, indent=2)
    print(len(final))

except FileNotFoundError:
    print("Error: The specified file was not found. Please ensure the path is correct.")
except json.JSONDecodeError:
    print("Error: The file could not be parsed as valid JSON.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
