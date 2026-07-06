"""
knowledge_base/embedder.py
Shared sentence-transformer embedding function for the retail_kb
collection. Local model, no external API call.
"""
from chromadb.utils import embedding_functions

EMBED_MODEL = "all-MiniLM-L6-v2"

_embedding_fn = None


def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL
        )
    return _embedding_fn
