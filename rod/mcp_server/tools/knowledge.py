
"""
mcp_server/tools/knowledge.py
 
TOOL 5: knowledge_search
    Required scope: read:knowledge
    DB: knowledge_base/chroma_db/ (ChromaDB collection: retail_kb)
    Input:  { query: str (required), n_results: int (optional, 1–5, default 2) }
    Output: { query, results: [{ document_id, category, title, excerpt, similarity_score }] }
 
Implementation notes:
    - Embeddings generated locally via all-MiniLM-L6-v2 — NO external API call.
    - Similarity score formula: 1 - cosine_distance (retail_kb collection uses
      hnsw:space="cosine" — see knowledge_base/service.py for why)
    - Must respond within 500ms.
    - Agent may call this multiple times per investigation with different queries.
    - ChromaDB metadata fields: category (SOP | Past Case), tags (comma-separated string)
    - Documents longer than one embedding chunk (see knowledge_base/chunking.py)
      are stored as multiple chunk rows sharing a parent_document_id — a hit's
      doc_id is always the parent id, chunk_index/total_chunks say which piece matched.
 
RBAC (2026-07-28): not touched by the store-scoped RBAC pass — SOPs/past cases in the
knowledge base have no store dimension at all, so there's nothing to scope. Left open to
managers and admins alike, same as before.
"""
# [actual implementation is in Soorya's branch — this file is a placeholder for project structure clarity]
# tools/tool_9_knowledge.py
# MCP Tool: knowledge_search
# Scope required: read:knowledge
# Queries ChromaDB retail_kb collection for relevant SOPs and past cases

from fastmcp import FastMCP

from knowledge_base.service import get_collection
from mcp_server.auth_middleware import check_scope, get_token_payload
from logging_config import get_logger

logger = get_logger("mcp.knowledge")

mcp = FastMCP("retail-knowledge")

DEFAULT_N_RESULTS = 2

@mcp.tool()
def knowledge_search(query: str, n_results: int = DEFAULT_N_RESULTS) -> dict:
    """
    Searches the retail knowledge base for SOPs and past cases relevant to query.

    query: natural-language search string (must be non-empty)
    n_results: number of results to return (default: 2)
    """
    err = check_scope(get_token_payload(), "read:knowledge", tool_name="knowledge_search")
    if err:
        return err

    if not query or not query.strip():
        return {
            "error": "EMPTY_QUERY",
            "message": "query must be a non-empty string",
            "tool": "knowledge_search"
        }

    if not (1 <= n_results <= 5):
        return {
            "error": "INVALID_N_RESULTS",
            "message": "n_results must be between 1 and 5",
            "tool": "knowledge_search"
        }

    try:
        collection = get_collection()

        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count())
        )

        hits = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            metadata = results["metadatas"][0][i]
            chunk_id = results["ids"][0][i]
            hits.append({
                "doc_id": metadata.get("parent_document_id", chunk_id),
                "text": results["documents"][0][i],
                "category": metadata.get("category"),
                "tags": metadata.get("tags"),
                "chunk_index": metadata.get("chunk_index", 0),
                "total_chunks": metadata.get("total_chunks", 1),
                # cosine space in Chroma returns distance = 1 - cosine_similarity,
                # so similarity is just 1 - distance (clamped for float noise).
                "similarity_score": round(max(0.0, min(1.0, 1 - distance)), 4)
            })

        return {
            "query": query,
            "n_results": len(hits),
            "results": hits,
            "tool": "knowledge_search"
        }

    except Exception as e:
        logger.error(
            "knowledge search failed",
            extra={"event": "knowledge_error", "error_type": type(e).__name__},
            exc_info=True,
        )
        return {
            "error": "KNOWLEDGE_ERROR",
            "message": str(e),
            "tool": "knowledge_search"
        }


if __name__ == "__main__":
    mcp.run()