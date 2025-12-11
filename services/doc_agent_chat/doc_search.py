import os
from typing import List, Optional
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from embeddings.embeddings import SearchResult
from util import create_logger

logger = create_logger("DocSearch")


class DocSearch:
    """
    Abstraction layer for document search.
    Designed to make switching from Pinecone to PostgreSQL easy.
    """

    def __init__(self, project_id: str, available_doc_uuids: List[str], index_name: str = "doc_agent"):
        self.project_id = project_id
        self.available_doc_uuids = available_doc_uuids
        self.index_name = index_name
        self.namespace = f"project-{project_id}"

        # Currently using Pinecone
        self.vectorstore = PineconeVectorStore(
            index_name=index_name,
            namespace=self.namespace,
            embedding=OpenAIEmbeddings()
        )
        logger.info(f"Initialized DocSearch for project {project_id}")

    def search(
        self,
        query: str,
        document_uuids: Optional[List[str]] = None,
        top_k: int = 5,
        threshold: float = 0.7
    ) -> List[SearchResult]:
        """
        Search documents with optional UUID filtering.
        DB-agnostic interface for easy switching to PostgreSQL later.
        """
        # Validate document_uuids if provided
        if document_uuids:
            document_uuids = self._validate_uuids(document_uuids)

        # Build filters
        filters = self._build_filters(document_uuids)
        logger.info(f"Searching with query: '{query}', filters: {filters}")

        # Search (currently Pinecone)
        scored_docs = self.vectorstore.similarity_search_with_score(
            query=query,
            k=top_k * 2,  # Get more results to filter by threshold
            filter=filters
        )

        # Filter by threshold and format results
        results = []
        for doc, score in scored_docs:
            if score >= threshold:
                results.append(SearchResult(
                    text=doc.page_content,
                    metadata=doc.metadata,
                    score=score
                ))
            if len(results) >= top_k:
                break

        logger.info(f"Found {len(results)} results above threshold {threshold}")
        return results

    def _validate_uuids(self, document_uuids: List[str]) -> List[str]:
        """Validate that requested UUIDs are in the available list."""
        validated = []
        for uuid in document_uuids:
            if uuid in self.available_doc_uuids:
                validated.append(uuid)
            else:
                logger.warning(f"Document UUID {uuid} not in available documents, skipping")

        if not validated and document_uuids:
            logger.warning("No valid document UUIDs provided, searching all documents")
            return None

        return validated if validated else None

    def _build_filters(self, document_uuids: Optional[List[str]] = None) -> Optional[dict]:
        """
        Build Pinecone metadata filters.
        Always filters by project_id, optionally by document_uuids.
        """
        conditions = []

        # Always filter by project_id
        conditions.append({"project_id": {"$eq": self.project_id}})

        # Optionally filter by document_uuids
        if document_uuids:
            if len(document_uuids) == 1:
                conditions.append({"document_uuid": {"$eq": document_uuids[0]}})
            else:
                conditions.append({"document_uuid": {"$in": document_uuids}})

        # Combine conditions
        if len(conditions) == 1:
            return conditions[0]
        else:
            return {"$and": conditions}
