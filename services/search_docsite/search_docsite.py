import os

import psycopg2
from dotenv import load_dotenv
from embeddings.embeddings import SearchResult
from langchain_openai import OpenAIEmbeddings
from pgvector import Vector
from pgvector.psycopg2 import register_vector
from search_docsite.pinecone_legacy_search import LegacyPineconeDocsiteSearch
from util import ApolloError, create_logger, get_db_connection

logger = create_logger("DocsiteSearch")

SCHEMA_MISSING_MESSAGE = (
    "Docsite schema not initialised — run embed_docsite with target=postgres"
)


def register_vector_type(conn):
    """Register the pgvector adapter on this connection."""
    register_vector(conn)


class DocsiteSearch:
    """
    Search embedded docsite chunks in Postgres using semantic (pgvector cosine),
    keyword (Postgres full-text search), or hybrid (Reciprocal Rank Fusion) strategies.

    :param batch_id: Explicit batch to search. If None, resolves to the newest 'complete' batch.
    :param default_top_k: Default number of results to return (default: 5)
    """

    def __init__(self, batch_id=None, default_top_k=5):
        self.default_top_k = default_top_k
        self._explicit_batch_id = batch_id
        self._embeddings = None

    @property
    def embeddings(self):
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings()
        return self._embeddings

    def _connect(self):
        """Open a connection with pgvector registered.
        """
        conn = get_db_connection()
        try:
            register_vector_type(conn)
        except psycopg2.ProgrammingError as exc:
            conn.close()
            raise ApolloError(503, SCHEMA_MISSING_MESSAGE, type="DATABASE_ERROR") from exc
        return conn

    def search(self, query, top_k=None, threshold=None, strategy='semantic', doc_title=None, docs_type=None):
        """
        Search docsite_chunks with optional filters.

        :param query: Search query string
        :param top_k: Number of results to return
        :param threshold: Cosine-similarity cutoff. Valid only for
            strategy='semantic'; raises for other strategies.
        :param strategy: 'semantic' | 'keyword' | 'hybrid' (default: 'semantic')
        :param doc_title: Filter by document title
        :param docs_type: Filter by document type
        :return: List of SearchResult objects
        """
        if threshold is not None and strategy != 'semantic':
            raise ApolloError(
                400,
                f"threshold is only supported for strategy='semantic', got '{strategy}'",
                type="BAD_REQUEST",
            )

        conn = self._connect()
        try:
            batch_id = self._explicit_batch_id or self._resolve_current_batch(conn)

            if strategy == 'semantic':
                return self._semantic_search(conn, batch_id, query, top_k, threshold, doc_title, docs_type)
            if strategy == 'keyword':
                return self._keyword_search(conn, batch_id, query, top_k, doc_title, docs_type)
            if strategy == 'hybrid':
                return self._hybrid_search(conn, batch_id, query, top_k, doc_title, docs_type)

            raise ApolloError(400, f"Unknown search strategy: {strategy}", type="BAD_REQUEST")
        finally:
            conn.close()

    def _resolve_current_batch(self, conn):
        """Find the newest complete batch id."""
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM docsite_batches WHERE status = 'complete' ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
        except psycopg2.errors.UndefinedTable as exc:
            raise ApolloError(503, SCHEMA_MISSING_MESSAGE, type="DATABASE_ERROR") from exc
        if row is None:
            raise ApolloError(404, "No complete docsite batch found", type="NOT_FOUND")
        return row[0]

    def _semantic_search(self, conn, batch_id, query, top_k, threshold, doc_title, docs_type):
        if top_k is None and threshold is None:
            top_k = self.default_top_k
        max_k = top_k or 50

        query_embedding = Vector(self.embeddings.embed_query(query))

        sql = """
        SELECT text, doc_title, docs_type, 1 - (embedding <=> %(query_embedding)s) AS score
        FROM docsite_chunks
        WHERE batch_id = %(batch_id)s
          AND (%(doc_title)s IS NULL OR doc_title = %(doc_title)s)
          AND (%(docs_type)s IS NULL OR docs_type = %(docs_type)s)
        ORDER BY embedding <=> %(query_embedding)s
        LIMIT %(max_k)s
        """
        params = {
            "query_embedding": query_embedding, "batch_id": batch_id,
            "doc_title": doc_title, "docs_type": docs_type, "max_k": max_k,
        }
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = []
        for text, title, dtype, score in rows:
            if threshold is not None and score < threshold:
                continue
            if top_k is not None and len(results) >= top_k and threshold is None:
                break
            results.append(SearchResult(text, {"doc_title": title, "docs_type": dtype}, score))

        logger.info(f"Semantic search returned {len(results)} results")
        return results

    def _keyword_search(self, conn, batch_id, query, top_k, doc_title, docs_type):
        max_k = top_k or self.default_top_k

        sql = """
        SELECT text, doc_title, docs_type,
               ts_rank_cd(text_search, plainto_tsquery('english', %(query)s)) AS score
        FROM docsite_chunks
        WHERE batch_id = %(batch_id)s
          AND text_search @@ plainto_tsquery('english', %(query)s)
          AND (%(doc_title)s IS NULL OR doc_title = %(doc_title)s)
          AND (%(docs_type)s IS NULL OR docs_type = %(docs_type)s)
        ORDER BY score DESC
        LIMIT %(max_k)s
        """
        params = {"query": query, "batch_id": batch_id, "doc_title": doc_title, "docs_type": docs_type, "max_k": max_k}
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = [SearchResult(text, {"doc_title": title, "docs_type": dtype}, score) for text, title, dtype, score in rows]
        logger.info(f"Keyword search returned {len(results)} results")
        return results

    def _hybrid_search(self, conn, batch_id, query, top_k, doc_title, docs_type):
        max_k = top_k or self.default_top_k
        candidate_k = 50

        query_embedding = Vector(self.embeddings.embed_query(query))

        sql = """
        WITH semantic AS (
          SELECT id, text, doc_title, docs_type,
                 ROW_NUMBER() OVER (ORDER BY embedding <=> %(query_embedding)s) AS rnk
          FROM docsite_chunks
          WHERE batch_id = %(batch_id)s
            AND (%(doc_title)s IS NULL OR doc_title = %(doc_title)s)
            AND (%(docs_type)s IS NULL OR docs_type = %(docs_type)s)
          ORDER BY embedding <=> %(query_embedding)s
          LIMIT %(candidate_k)s
        ),
        keyword AS (
          SELECT id, text, doc_title, docs_type,
                 ROW_NUMBER() OVER (ORDER BY ts_rank_cd(text_search, plainto_tsquery('english', %(query)s)) DESC) AS rnk
          FROM docsite_chunks
          WHERE batch_id = %(batch_id)s
            AND text_search @@ plainto_tsquery('english', %(query)s)
            AND (%(doc_title)s IS NULL OR doc_title = %(doc_title)s)
            AND (%(docs_type)s IS NULL OR docs_type = %(docs_type)s)
          ORDER BY rnk
          LIMIT %(candidate_k)s
        )
        SELECT COALESCE(s.text, k.text) AS text,
               COALESCE(s.doc_title, k.doc_title) AS doc_title,
               COALESCE(s.docs_type, k.docs_type) AS docs_type,
               COALESCE(1.0::float8 / (60 + s.rnk), 0) + COALESCE(1.0::float8 / (60 + k.rnk), 0) AS score
        FROM semantic s FULL OUTER JOIN keyword k ON s.id = k.id
        ORDER BY score DESC
        LIMIT %(max_k)s
        """
        params = {
            "query_embedding": query_embedding, "query": query, "batch_id": batch_id,
            "doc_title": doc_title, "docs_type": docs_type, "candidate_k": candidate_k, "max_k": max_k,
        }
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = [
            SearchResult(text, {"doc_title": title, "docs_type": dtype}, float(score))
            for text, title, dtype, score in rows
        ]
        logger.info(f"Hybrid search returned {len(results)} results")
        return results


BACKEND_INDEX_PARAMS = {
    "postgres": ["batch_id", "default_top_k"],
    "pinecone": ["collection_name", "index_name", "default_top_k", "embeddings"],
}


def resolve_backend(override=None):
    """Return the search class for the configured backend.

    :param override: Backend name that is prioritised over DOCSITE_SEARCH_BACKEND
    """
    name = override or os.environ.get("DOCSITE_SEARCH_BACKEND", "pinecone")
    if name not in BACKEND_INDEX_PARAMS:
        raise ApolloError(400, f"Unknown backend '{name}'. Expected 'pinecone' or 'postgres'", type="BAD_REQUEST")
    return DocsiteSearch if name == "postgres" else LegacyPineconeDocsiteSearch


def main(data):
    logger.info("Starting...")

    required_fields = ["query"]
    missing = [field for field in required_fields if field not in data]
    if missing:
        logger.error(f"Missing required fields in data: {', '.join(missing)}")
        return None

    backend = data.get("backend") or os.environ.get("DOCSITE_SEARCH_BACKEND", "pinecone")
    search_cls = resolve_backend(backend)

    search_params = {"query": data["query"]}
    optional_search_params = ["docs_type", "doc_title", "top_k", "threshold", "strategy"]
    for key in optional_search_params:
        if key in data:
            search_params[key] = data[key]

    index_params = {key: data[key] for key in BACKEND_INDEX_PARAMS[backend] if key in data}

    load_dotenv(override=True)
    openai_api_key = os.environ.get('OPENAI_API_KEY')
    if not openai_api_key:
        msg = "Missing API key: OPENAI_API_KEY"
        logger.error(msg)
        raise ApolloError(500, msg, type="BAD_REQUEST")

    logger.info(f"Searching docsite via the {backend} backend")

    docsite_search = search_cls(**index_params)
    results = docsite_search.search(**search_params)

    return [result.to_json() for result in results]


if __name__ == "__main__":
    main({})
