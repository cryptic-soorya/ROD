"""
knowledge_base/pg_vector_client.py
Postgres + pgvector backed replacement for the old local ChromaDB
PersistentClient (knowledge_base/chroma_client.py, removed). Every dev
used to get their own ./knowledge_base/chroma_db/ directory seeded
independently — nobody shared a knowledge base, and CRUD edits from one
person's Admin session were invisible to everyone else. This puts the
retail_kb collection in the same Supabase Postgres DB every other domain
already uses, via db_pool, so the whole team reads/writes one shared
vector store.

Exposes a small Chroma-collection-shaped wrapper (PgVectorCollection)
implementing only what knowledge_base/service.py's callers actually use
(count/upsert/get/delete/query) so knowledge_base/router.py and
mcp_server/tools/knowledge.py needed no changes beyond their import.
"""
import os

from pgvector import Vector
from pgvector.psycopg2 import register_vector

from db_pool import get_conn, put_conn

KNOWLEDGE_DB_URL = os.getenv("KNOWLEDGE_DB_URL", os.getenv("DATABASE_URL"))

SCHEMA = "knowledge"
TABLE = f"{SCHEMA}.chunks"     # the one shared table every document's chunks live in

# all-MiniLM-L6-v2 output size — fixed by the embedding model, not
# configurable independently of it.
EMBED_DIM = 384

_schema_ready = False   # so we only check/create the table once per process, not every call


# Makes sure the pgvector extension, schema, table, and indexes all exist —
# basically "first-time setup", but safe to call every time (it does nothing
# if everything's already there).
def ensure_schema(dsn: str = KNOWLEDGE_DB_URL) -> None:
    """Creates the pgvector extension, schema, table and indexes if they
    don't exist yet. Idempotent, safe to call from every process that
    imports this module (app startup, seed scripts, tests)."""
    global _schema_ready
    if _schema_ready:
        return

    conn = get_conn(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")  # turns on Postgres's vector-search feature
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            # The actual table: one row per chunk, storing its text + its embedding vector.
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    id TEXT PRIMARY KEY,
                    parent_document_id TEXT NOT NULL,
                    chunk_index INT NOT NULL DEFAULT 0,
                    total_chunks INT NOT NULL DEFAULT 1,
                    category TEXT,
                    tags TEXT,
                    document TEXT NOT NULL,
                    full_text TEXT,
                    embedding vector({EMBED_DIM}) NOT NULL
                )
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS chunks_parent_document_id_idx
                ON {TABLE} (parent_document_id)
            """)
            # HNSW + vector_cosine_ops so `embedding <=> query` returns
            # cosine distance (1 - cosine_similarity) — same distance
            # semantics the old collection's hnsw:space="cosine" metadata
            # gave us, which mcp_server/tools/knowledge.py's
            # `1 - distance` similarity_score formula depends on.
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
                ON {TABLE} USING hnsw (embedding vector_cosine_ops)
            """)
        conn.commit()
        _schema_ready = True
    finally:
        put_conn(dsn, conn)


_METADATA_COLUMNS = (
    "id, document, category, tags, parent_document_id, "
    "chunk_index, total_chunks, full_text"
)


# Reshapes one database row into the "metadata" dict shape the rest of the
# codebase (router.py, mcp_server/tools/knowledge.py) expects.
def _row_to_metadata(row: dict) -> dict:
    return {
        "category": row["category"],
        "tags": row["tags"],
        "parent_document_id": row["parent_document_id"],
        "chunk_index": row["chunk_index"],
        "total_chunks": row["total_chunks"],
        "full_text": row["full_text"],
    }


# This class is the whole "database layer" for the knowledge base — it's the
# only thing that talks SQL. Everything else (router.py, knowledge_search tool)
# just calls these simple methods: count / upsert / delete / get / query.
class PgVectorCollection:
    """Chroma-collection-shaped facade over the knowledge.chunks table."""

    def __init__(self, dsn: str, embedding_function):
        self._dsn = dsn
        self._embed = embedding_function

    # How many chunk rows are currently stored.
    def count(self) -> int:
        conn = get_conn(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS n FROM {TABLE}")
                return cur.fetchone()["n"]
        finally:
            put_conn(self._dsn, conn)

    # Insert new chunk rows, or overwrite them if the id already exists
    # ("upsert" = update-or-insert). This is what makes a document searchable.
    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        # Turn the chunk texts into embedding vectors before saving.
        embeddings = self._embed(documents)
        conn = get_conn(self._dsn)
        try:
            register_vector(conn)
            with conn.cursor() as cur:
                for doc_id, doc_text, metadata, embedding in zip(ids, documents, metadatas, embeddings):
                    cur.execute(f"""
                        INSERT INTO {TABLE}
                            (id, parent_document_id, chunk_index, total_chunks,
                             category, tags, document, full_text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            parent_document_id = EXCLUDED.parent_document_id,
                            chunk_index = EXCLUDED.chunk_index,
                            total_chunks = EXCLUDED.total_chunks,
                            category = EXCLUDED.category,
                            tags = EXCLUDED.tags,
                            document = EXCLUDED.document,
                            full_text = EXCLUDED.full_text,
                            embedding = EXCLUDED.embedding
                    """, (
                        doc_id,
                        metadata.get("parent_document_id", doc_id),
                        metadata.get("chunk_index", 0),
                        metadata.get("total_chunks", 1),
                        metadata.get("category"),
                        metadata.get("tags"),
                        doc_text,
                        metadata.get("full_text"),
                        Vector(embedding),
                    ))
            conn.commit()
        finally:
            put_conn(self._dsn, conn)

    # Permanently removes rows by id. No soft-delete/undo.
    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        conn = get_conn(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {TABLE} WHERE id = ANY(%s)", (list(ids),))
            conn.commit()
        finally:
            put_conn(self._dsn, conn)

    # Plain lookup (no similarity search) — by exact ids, by parent document,
    # or "give me everything" if neither is given. Used for listing/checking existence.
    def get(self, where: dict | None = None, ids: list[str] | None = None) -> dict:
        conn = get_conn(self._dsn)
        try:
            with conn.cursor() as cur:
                if ids is not None:
                    cur.execute(
                        f"SELECT {_METADATA_COLUMNS} FROM {TABLE} WHERE id = ANY(%s)",
                        (list(ids),),
                    )
                elif where and "parent_document_id" in where:
                    cur.execute(
                        f"SELECT {_METADATA_COLUMNS} FROM {TABLE} "
                        f"WHERE parent_document_id = %s ORDER BY chunk_index",
                        (where["parent_document_id"],),
                    )
                else:
                    cur.execute(
                        f"SELECT {_METADATA_COLUMNS} FROM {TABLE} "
                        f"ORDER BY parent_document_id, chunk_index"
                    )
                rows = cur.fetchall()
        finally:
            put_conn(self._dsn, conn)

        return {
            "ids": [r["id"] for r in rows],
            "documents": [r["document"] for r in rows],
            "metadatas": [_row_to_metadata(r) for r in rows],
        }

    # THE semantic search method — this is what knowledge_search actually calls.
    # Turns the search text into a vector, then asks Postgres for the
    # n_results closest-matching chunks by vector distance (smaller = more similar).
    def query(self, query_texts: list[str], n_results: int) -> dict:
        if n_results <= 0:
            return {"ids": [[]], "distances": [[]], "documents": [[]], "metadatas": [[]]}

        # Embed the search query the same way documents were embedded, so they're comparable.
        query_embedding = Vector(self._embed(query_texts)[0])
        conn = get_conn(self._dsn)
        try:
            register_vector(conn)
            with conn.cursor() as cur:
                # "<=>" is pgvector's cosine-distance operator — ranks rows by
                # how close their embedding is to the query's embedding.
                cur.execute(f"""
                    SELECT {_METADATA_COLUMNS}, embedding <=> %s AS distance
                    FROM {TABLE}
                    ORDER BY embedding <=> %s
                    LIMIT %s
                """, (query_embedding, query_embedding, n_results))
                rows = cur.fetchall()
        finally:
            put_conn(self._dsn, conn)

        return {
            "ids": [[r["id"] for r in rows]],
            "distances": [[r["distance"] for r in rows]],
            "documents": [[r["document"] for r in rows]],
            "metadatas": [[_row_to_metadata(r) for r in rows]],
        }
