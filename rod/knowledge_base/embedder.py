"""
knowledge_base/embedder.py
Shared sentence-transformer embedding function for the retail_kb
collection. Local model, no external API call.
"""
import os

# Must be set before chromadb pulls in sentence_transformers/huggingface_hub —
# otherwise a network hiccup makes SentenceTransformer's startup adapter-config
# check hang/retry against huggingface.co even though the model is already
# cached locally. HF_HUB_OFFLINE forces cache-only loading, matching this
# module's "no external API call" contract.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

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
