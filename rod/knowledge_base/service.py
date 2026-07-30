"""
knowledge_base/service.py
Shared retail_kb collection accessor — Postgres + pgvector backed (see
knowledge_base/pg_vector_client.py) — used by both the knowledge CRUD
router and the knowledge_search MCP tool so they never point at two
different vector stores. This is also what makes the knowledge base
shared across the team: everyone's app points at the same Supabase
Postgres DB, instead of each dev seeding their own local ChromaDB
directory.
"""
from knowledge_base.embedder import get_embedding_function
from knowledge_base.pg_vector_client import KNOWLEDGE_DB_URL, PgVectorCollection, ensure_schema

_collection = None  # cached so we only set this up once per process, not once per request


# The single entry point everyone uses to reach the knowledge base.
# First call: makes sure the database table exists, then builds the collection object.
# Every later call: just hands back the same cached collection.
def get_collection() -> PgVectorCollection:
    global _collection
    if _collection is None:
        ensure_schema()
        _collection = PgVectorCollection(KNOWLEDGE_DB_URL, get_embedding_function())
    return _collection
