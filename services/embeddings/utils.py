from langchain_community.document_loaders import JSONLoader

def load_json(file_path, jq_schema):
    """Load JSON documents."""
    loader = JSONLoader(
        file_path=file_path,
        jq_schema=jq_schema,
        text_content=False
    )
    return loader.load()