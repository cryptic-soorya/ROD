# tools/tool_9_knowledge.py
# MCP Tool: knowledge_search
# Scope required: read:knowledge
# Queries ChromaDB retail_kb collection for relevant SOPs and past cases

import os
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
COLLECTION_NAME = "retail_kb"
DEFAULT_N_RESULTS = 2

_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

def knowledge_search(query: str, n_results: int = DEFAULT_N_RESULTS) -> dict:
    """
    Searches the retail knowledge base for SOPs and past cases relevant to query.

    query: natural-language search string (must be non-empty)
    n_results: number of results to return (default: 2)
    """
    if not query or not query.strip():
        return {
            "error": "EMPTY_QUERY",
            "message": "query must be a non-empty string",
            "tool": "knowledge_search"
        }

    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=_embedding_fn
        )

        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count())
        )

        hits = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            hits.append({
                "doc_id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "category": results["metadatas"][0][i].get("category"),
                "tags": results["metadatas"][0][i].get("tags"),
                "similarity_score": round(1 - distance, 4)
            })

        return {
            "query": query,
            "n_results": len(hits),
            "results": hits,
            "tool": "knowledge_search"
        }

    except Exception as e:
        return {
            "error": "KNOWLEDGE_ERROR",
            "message": str(e),
            "tool": "knowledge_search"
        }
