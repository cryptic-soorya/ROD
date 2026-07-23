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
        embedding_function=get_embedding_function(),
        # Chroma's default is L2 (squared euclidean). L2 is sensitive to
        # embedding magnitude, not just direction — two documents that are
        # semantically identical but embedded at different vector lengths
        # (e.g. one longer chunk vs. one shorter chunk of the same idea)
        # can score as less similar than they should. Sentence-transformer
        # embeddings are meant to be compared by *direction*, which is what
        # cosine measures, so it's the right space for text similarity here.
        # NOTE: this only takes effect on collection *creation* — an
        # existing collection keeps whatever space it was created with, so
        # switching this requires deleting and re-seeding retail_kb once.
        metadata={"hnsw:space": "cosine"},
    )
