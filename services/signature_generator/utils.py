import spacy
from spacy.tokens import Doc, Token

from util import create_logger

logger = create_logger("signature_generator.utils")

# Load the English language model
nlp = spacy.load("en_core_web_sm")


def trim_signature(signature: str) -> str:
    end_tokens = "==="
    if end_tokens in signature:
        logger.info("Trimming the signature at the end token")
        signature = signature[: signature.find(end_tokens)]
    else:
        logger.warning("End token not found in the signature")
    return signature


def extract_parameter(param: dict[str]) -> list[str]:
    if "schema" in param and "type" in param["schema"]:
        return {"name": param["name"], "type": param["schema"]["type"]}
    return None


def extract_schema(
    response_code: str,
    response: dict[str, any],
    spec: dict[str, any],
) -> dict[str]:
    content = response.get("content")
    if content:
        content_type = next(iter(content.keys()))
        schema = content[content_type].get("schema")
        if schema:
            schema_type, schema_object = get_schema_info(schema, spec)
            return {
                "status_code": response_code,
                "content_type": content_type,
                "schema_type": schema_type,
                "schema_object": schema_object,
            }
    return None


def get_schema_info(schema: dict[str, any], spec: dict[str, any]) -> list[dict]:
    if "$ref" in schema:
        schema_type = schema["$ref"].split("/")[-1]
        properties = spec["components"]["schemas"][schema_type]["properties"]
        return schema_type, [{"name": key, "type": value["type"]} for key, value in properties.items()]
    elif "items" in schema:
        items = schema["items"]
        if "$ref" in items:
            schema_type = items["$ref"].split("/")[-1]
            properties = spec["components"]["schemas"][schema_type]["properties"]
            schema_type = f"list[{schema_type}]"
            return schema_type, [{"name": key, "type": value["type"]} for key, value in properties.items()]
    else:
        schema_type = schema.get("type")
        return schema_type, [
            {"name": key, "type": value["type"]} for key, value in schema.get("properties", {}).items()
        ]


def parse_openapi_spec(spec: dict[str, any]) -> list[dict]:
    results = []
    try:
        for path, path_item in spec["paths"].items():
            current_path = {"path": path, "operations": []}
            for method, operation in path_item.items():
                current_operation = {
                    "method": method.upper(),
                    "parameters": [
                        param for param in (extract_parameter(p) for p in operation.get("parameters", [])) if param
                    ],
                    "responses": [
                        extract_schema(response_code, response, spec)
                        for response_code, response in operation.get(
                            "responses",
                            {},
                        ).items()
                        if response
                    ],
                }
                current_path["operations"].append(current_operation)
            results.append(current_path)
    except Exception as e:
        logger.error(f"Error occurred during parsing: {e}")
    return results


def lemmatize_action(action: str) -> str:
    # Lemmatize the action to get its base form
    doc = nlp(action)
    return doc[0].lemma_


def find_closest_verb(endpoint_token: Token) -> str:
    # Iterate over the ancestors of the token (including itself) until a verb is found
    current_token = endpoint_token
    while current_token is not None and (current_token.pos_ != "VERB" or current_token.text.lower() == "endpoint"):
        current_token = current_token.head

    # If a verb is found, return it; otherwise, return None
    return (
        lemmatize_action(current_token.text.lower())
        if current_token is not None and current_token.pos_ == "VERB"
        else None
    )


def find_related_verb(endpoint_token: Token, doc: Doc) -> str:
    # Find the verb related to the endpoint by searching for the nearest verb to the endpoint
    for token in doc:
        if token.head == endpoint_token and token.pos_ == "VERB" and token.text.lower() != "endpoint":
            return lemmatize_action(token.text.lower())
    return None


def format_api_output(api_info: dict[str, any]) -> str:
    if api_info:
        method = api_info.get("method")
        endpoint = api_info.get("endpoint")
        parameters = api_info.get("parameters", [])
        responses = api_info.get("responses", [])

        formatted_output = f"{method} {endpoint}\n"

        if parameters:
            formatted_output += "    Parameters:\n"
            for param in parameters:
                formatted_output += f"    - {param['name']}: {param['type']}\n"

        for response in responses:
            if response:
                status_code = response.get("status_code")
                schema_type = response.get("schema_type")
                schema_object = response.get("schema_object", [])

                formatted_output += f"    Response {status_code}:\n"
                formatted_output += f"    - {schema_type}:\n"

                for prop in schema_object:
                    formatted_output += f"      {prop['name']}: {prop['type']}\n"

        return formatted_output

    return None


def extract_api_info(api_spec: dict, instruction: str) -> dict[str, any]:
    doc = nlp(instruction)

    # Initialize variables to store extracted information
    endpoint = None
    action = None

    # Define mapping of action keywords to HTTP methods
    action_method_mapping = {
        "read": "GET",
        "get": "GET",
        "access": "GET",
        "update": "PUT",
        "create": "POST",
        "delete": "DELETE",
        "list": "GET",
        "retrieve": "GET",
        "modify": "PUT",
        "add": "POST",
        # Add more mappings as needed
    }

    # Iterate through tokens in the processed text
    for token in doc:
        # Check if the token is an endpoint
        if token.text.startswith("/") and endpoint is None:
            endpoint = token.text
            # Find the related verb to the endpoint
            action = find_closest_verb(token)

    # Find the corresponding operation in the API specification
    for endpoint_info in api_spec:
        if "path" in endpoint_info and endpoint_info["path"] == endpoint:
            operations = endpoint_info.get("operations", [])
            for operation in operations:
                method = action_method_mapping.get(action)
                if method and "method" in operation and operation["method"].upper() == method:
                    api_info = {
                        "endpoint": endpoint,
                        "action": action,
                        "method": method,
                        "parameters": operation.get("parameters", []),
                        "responses": operation.get("responses", []),
                    }
                    return format_api_output(api_info)

    # Return None if no matching information is found
    return None
