"""
knowledge_base/chroma_client.py
Shared ChromaDB PersistentClient factory — one client instance for the
whole process, reused by knowledge_base/service.py.
"""
import os
import chromadb

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./knowledge_base/chroma_db")

_client = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _client
