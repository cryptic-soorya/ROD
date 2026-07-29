"""
knowledge_base/embedder.py
Shared sentence-transformer embedding function for the retail_kb table
(knowledge_base/pg_vector_client.py). Local model, no external API call —
only the vector *storage* moved to Postgres/pgvector, embedding generation
is unchanged.
"""
import os

# Must be set before sentence_transformers/huggingface_hub load — otherwise
# a network hiccup makes SentenceTransformer's startup adapter-config check
# hang/retry against huggingface.co even though the model is already cached
# locally. HF_HUB_OFFLINE forces cache-only loading, matching this module's
# "no external API call" contract.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from sentence_transformers import SentenceTransformer

EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM = 384

_model = None


def get_embedding_function():
    """Returns a callable: list[str] -> list[list[float]]. Was previously
    a chromadb SentenceTransformerEmbeddingFunction instance (same call
    signature) — chromadb is gone now that storage is pgvector, so this
    wraps the sentence-transformers model directly."""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)

    def embed(texts: list[str]) -> list[list[float]]:
        return _model.encode(list(texts), convert_to_numpy=True).tolist()

    return embed
