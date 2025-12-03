import os
import psycopg2


def get_db_connection():
    """Get database connection from POSTGRES_URL environment variable.

    Returns:
        psycopg2.connection or None: Database connection if POSTGRES_URL is set, None otherwise
    """
    db_url = os.environ.get("POSTGRES_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return None
