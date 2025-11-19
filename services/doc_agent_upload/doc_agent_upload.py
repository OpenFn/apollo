import os
import uuid
from typing import Dict, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from util import create_logger, ApolloError
from doc_agent_upload.doc_processor import DocProcessor
from doc_agent_upload.doc_indexer import DocIndexer

logger = create_logger("doc_agent_upload")

@dataclass
class Payload:
    doc_url: str
    user_description: str
    project_id: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        if "doc_url" not in data:
            raise ValueError("'doc_url' is required")
        if "user_description" not in data:
            raise ValueError("'user_description' is required")
        if "project_id" not in data:
            raise ValueError("'project_id' is required")

        return cls(
            doc_url=data["doc_url"],
            user_description=data["user_description"],
            project_id=data["project_id"]
        )


def main(data: dict) -> dict:
    try:
        logger.info("Starting document upload...")
        payload = Payload.from_dict(data)

        load_dotenv(override=True)
        OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
        PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')

        missing_keys = []
        if not OPENAI_API_KEY:
            missing_keys.append("OPENAI_API_KEY")
        if not PINECONE_API_KEY:
            missing_keys.append("PINECONE_API_KEY")

        if missing_keys:
            msg = f"Missing API keys: {', '.join(missing_keys)}"
            logger.error(msg)
            raise ApolloError(500, msg, type="MISSING_API_KEY")

        # Generate document UUID
        document_uuid = str(uuid.uuid4())
        logger.info(f"Generated document UUID: {document_uuid}")

        # Process document - fetch and chunk
        processor = DocProcessor(chunk_size=512, chunk_overlap=50)
        doc_title, chunks = processor.process_document(payload.doc_url)
        logger.info(f"Document processed: {len(chunks)} chunks created")

        # Upload to Pinecone
        indexer = DocIndexer(
            project_id=payload.project_id,
            index_name="doc-agent"
        )
        indexer.upload_document(
            chunks=chunks,
            document_uuid=document_uuid,
            doc_title=doc_title,
            user_description=payload.user_description
        )
        logger.info(f"Document uploaded to Pinecone successfully")

        return {
            "document_uuid": document_uuid,
            "doc_title": doc_title,
            "chunks_uploaded": len(chunks),
            "status": "success"
        }

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise ApolloError(400, str(e), type="BAD_REQUEST")
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        raise ApolloError(500, str(e), type="INTERNAL_ERROR")


if __name__ == "__main__":
    main()
