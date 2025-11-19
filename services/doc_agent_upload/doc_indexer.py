import os
import time
from typing import List
import pandas as pd
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_community.document_loaders import DataFrameLoader
from util import create_logger, ApolloError

logger = create_logger("DocIndexer")


class DocIndexer:
    def __init__(self, project_id: str, index_name: str = "doc-agent", dimension: int = 1536):
        self.project_id = project_id
        self.index_name = index_name
        self.dimension = dimension
        self.namespace = f"project-{project_id}"
        self.embeddings = OpenAIEmbeddings()
        self.pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))

        if not self._index_exists():
            self._create_index()

        self.index = self.pc.Index(self.index_name)
        self.vectorstore = PineconeVectorStore(
            index_name=index_name,
            namespace=self.namespace,
            embedding=self.embeddings
        )

    def upload_document(
        self,
        chunks: List[str],
        document_uuid: str,
        doc_title: str,
        user_description: str
    ):
        """Upload document chunks to Pinecone."""
        logger.info(f"Uploading {len(chunks)} chunks for document {document_uuid}")

        # Prepare data
        df = self._prepare_dataframe(chunks, document_uuid, doc_title, user_description)

        # Load into LangChain documents
        loader = DataFrameLoader(df, page_content_column="text")
        docs = loader.load()

        # Upload to Pinecone
        self.vectorstore.add_documents(documents=docs)
        logger.info(f"Uploaded {len(docs)} documents to namespace {self.namespace}")

    def _prepare_dataframe(
        self,
        chunks: List[str],
        document_uuid: str,
        doc_title: str,
        user_description: str
    ) -> pd.DataFrame:
        """Prepare dataframe with chunks and metadata."""
        data = []
        for chunk in chunks:
            data.append({
                "text": chunk,
                "project_id": self.project_id,
                "document_uuid": document_uuid,
                "doc_title": doc_title,
                "user_description": user_description
            })

        return pd.DataFrame(data)

    def _create_index(self):
        """Create new Pinecone index if it doesn't exist."""
        logger.info(f"Creating new index: {self.index_name}")
        self.pc.create_index(
            name=self.index_name,
            dimension=self.dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )

        # Wait for index to be ready
        while not self.pc.describe_index(self.index_name).status["ready"]:
            time.sleep(1)
        logger.info(f"Index {self.index_name} created and ready")

    def _index_exists(self) -> bool:
        """Check if index exists."""
        existing_indexes = [index_info["name"] for index_info in self.pc.list_indexes()]
        return self.index_name in existing_indexes
