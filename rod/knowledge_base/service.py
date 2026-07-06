"""
knowledge_base/service.py
Shared retail_kb collection accessor, used by both the knowledge CRUD
router and the knowledge_search MCP tool so they never point at two
different ChromaDB collections/paths.
"""
from knowledge_base.chroma_client import get_client
from knowledge_base.embedder import get_embedding_function

COLLECTION_NAME = "retail_kb"


def get_collection():
    client = get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function()
    )
