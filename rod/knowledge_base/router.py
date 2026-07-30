"""
knowledge_base/router.py

"""
# [actual implementation is in Soorya's branch]
# knowledge_api.py
# FastAPI endpoints for knowledge base management.
# Only Admin role can use these — write:knowledge scope required.
#
# POST   /api/v1/detective/knowledge              → add document
# PUT    /api/v1/detective/knowledge/{documentId} → update document  
# DELETE /api/v1/detective/knowledge/{documentId} → delete document
#
# Run: uvicorn knowledge_api:app --reload --port 8001

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import os
import jwt
import time

from knowledge_base.service import get_collection
from knowledge_base.chunking import chunk_text
from logging_config import get_logger

logger = get_logger("knowledge_base.router")

app = FastAPI(title="ROD Knowledge API")

# ── ChromaDB setup ─────────────────────────────────────────────────────────
# Same collection your knowledge_search tool reads from (shared via
# knowledge_base/service.py) — changes here are immediately visible to
# the MCP tool, no restart needed.

JWT_SECRET  = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
_collection = get_collection()  # the shared vector store table (knowledge.chunks in Postgres)


# ── Auth helper ────────────────────────────────────────────────────────────
# Decodes the Bearer token from the Authorization header.
# Returns the payload if valid, raises 401/403 if not.

def require_scope(authorization: str, required_scope: str) -> dict:
    """
    Validates JWT from Authorization header.
    Raises HTTPException 401 if token missing/invalid.
    Raises HTTPException 403 if required scope not present.
    """
    # No token at all, or wrong format -> reject immediately.
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning(
            "knowledge endpoint called with no Bearer token",
            extra={"event": "scope_denied", "error_type": "MISSING_BEARER_TOKEN"},
        )
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.split(" ")[1]  # strip "Bearer " prefix

    # Decode + verify the token's signature and expiry.
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning(
            "knowledge endpoint token expired",
            extra={"event": "scope_denied", "error_type": "ExpiredSignatureError"},
        )
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning(
            f"knowledge endpoint token invalid ({type(e).__name__})",
            extra={"event": "scope_denied", "error_type": type(e).__name__},
        )
        raise HTTPException(status_code=401, detail="Invalid token")

    # Token is valid, but does it actually have permission for this action?
    # e.g. write:knowledge is Admin-only.
    scopes = payload.get("scopes", [])
    if required_scope not in scopes:
        logger.warning(
            f"knowledge endpoint denied — missing scope '{required_scope}'",
            extra={"event": "scope_denied", "error_type": "MISSING_SCOPE"},
        )
        raise HTTPException(
            status_code=403,
            detail=f"Admin role required. Missing scope: {required_scope}"
        )

    return payload


# ── Request/Response models ────────────────────────────────────────────────
# Pydantic models define the shape of JSON bodies.
# FastAPI validates incoming requests against these automatically.

class AddDocumentRequest(BaseModel):
    document_text: str
    category: str           # "SOP" or "Past Case"
    tags: Optional[list[str]] = []

class UpdateDocumentRequest(BaseModel):
    document_text: str
    category: str
    tags: Optional[list[str]] = []


# ── Chunking helpers ────────────────────────────────────────────────────────
# A document longer than one embedding chunk (knowledge_base/chunking.py) is
# stored as multiple rows sharing a parent_document_id, so the public
# document_id from the API always stays stable regardless of chunk count.
# Row 0 of each document also carries the original, unchunked text under
# full_text, so GET can return exactly what was submitted rather than a
# reconstruction with overlap artifacts.

# Splits one document into embedding-sized chunks and builds the id/text/
# metadata lists needed to save them all as rows in the vector store.
def _build_chunk_rows(document_id: str, document_text: str, category: str, tags_str: str):
    chunks = chunk_text(document_text)
    ids = [document_id] if len(chunks) == 1 else [f"{document_id}__{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "category": category,
            "tags": tags_str,
            "parent_document_id": document_id,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "full_text": document_text,
        }
        for i in range(len(chunks))
    ]
    return ids, chunks, metadatas


# Finds every stored chunk row that belongs to a given document, so update/delete
# can act on all of them, not just the first one.
def _existing_chunk_ids(document_id: str) -> list[str]:
    """Finds every chunk row for a document_id, including legacy single-row
    documents (e.g. seed data) stored without a parent_document_id at all."""
    by_parent = _collection.get(where={"parent_document_id": document_id})
    if by_parent["ids"]:
        return list(by_parent["ids"])
    direct = _collection.get(ids=[document_id])
    return list(direct["ids"])


# ── GET /api/v1/detective/knowledge ───────────────────────────────────────
# Lists every document in the vector store. Any authenticated role with
# read:knowledge can browse (same scope knowledge_search itself requires) —
# only writes are admin-only.

@app.get("/api/v1/detective/knowledge")
def list_knowledge_documents(authorization: str = Header(default=None)):
    require_scope(authorization, "read:knowledge")

    # Fetch every row from the vector store, then rebuild them into one entry per document.
    existing = _collection.get()
    documents = []
    for doc_id, text, metadata in zip(
        existing["ids"], existing["documents"], existing["metadatas"]
    ):
        metadata = metadata or {}
        # Only chunk 0 represents the document in the listing — chunks 1+
        # are the same document's later fragments, not separate documents.
        if metadata.get("chunk_index", 0) != 0:
            continue
        tags_str = metadata.get("tags", "")
        documents.append({
            "document_id": metadata.get("parent_document_id", doc_id),
            "document_text": metadata.get("full_text", text),
            "category": metadata.get("category", ""),
            "tags": tags_str.split(",") if tags_str else [],
            "chunk_count": metadata.get("total_chunks", 1),
        })

    return {"documents": documents}


# ── POST /api/v1/detective/knowledge ──────────────────────────────────────
# Adds a new document to the vector store.
# Admin only (write:knowledge scope).
# Document is immediately searchable — no restart needed.

@app.post("/api/v1/detective/knowledge", status_code=201)
def add_knowledge_document(
    body: AddDocumentRequest,
    authorization: str = Header(default=None)
):
    # Check Admin scope first
    require_scope(authorization, "write:knowledge")

    # Validate document_text — must not be empty
    if not body.document_text or not body.document_text.strip():
        raise HTTPException(status_code=400, detail="document_text must not be empty")

    # Spec says max 2000 characters — chunking required for longer docs
    if len(body.document_text) > 2000:
        raise HTTPException(
            status_code=400,
            detail=f"document_text exceeds 2000 character limit ({len(body.document_text)} chars). Split into smaller chunks."
        )

    # Validate category — only these two are allowed
    valid_categories = {"SOP", "Past Case"}
    if body.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of: {', '.join(valid_categories)}"
        )

    # Generate a document ID based on timestamp
    # In production this would be a proper sequence — fine for now
    doc_id = f"DOC-{int(time.time())}"
    tags_str = ",".join(body.tags) if body.tags else ""

    # Split into embedding-sized chunks (knowledge_base/chunking.py) and
    # upsert each as its own row — the embedding is what makes it
    # semantically searchable, generated per chunk, not per whole document.
    ids, chunks, metadatas = _build_chunk_rows(doc_id, body.document_text, body.category, tags_str)
    # Save the chunks (this also generates the embeddings) — from this point on
    # the document is instantly findable by knowledge_search.
    _collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)

    return {
        "document_id": doc_id,
        "category": body.category,
        "tags": body.tags,
        "chunk_count": len(chunks),
        "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": f"Document embedded and indexed as {len(chunks)} chunk(s). Immediately searchable."
    }


# ── PUT /api/v1/detective/knowledge/{documentId} ──────────────────────────
# Updates an existing document — re-embeds it with new text.
# Admin only. Immediate effect.

@app.put("/api/v1/detective/knowledge/{document_id}")
def update_knowledge_document(
    document_id: str,
    body: UpdateDocumentRequest,
    authorization: str = Header(default=None)
):
    require_scope(authorization, "write:knowledge")

    # Check document exists before updating
    existing_ids = _existing_chunk_ids(document_id)
    # (validation below is the same rules as add_knowledge_document above)
    if not existing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found"
        )

    if not body.document_text or not body.document_text.strip():
        raise HTTPException(status_code=400, detail="document_text must not be empty")

    if len(body.document_text) > 2000:
        raise HTTPException(status_code=400, detail="document_text exceeds 2000 character limit")

    tags_str = ",".join(body.tags) if body.tags else ""

    # Chunk count can change between edits (e.g. text got longer/shorter),
    # so the old rows must be dropped rather than upserted over — an upsert
    # can't shrink a document from 3 chunks down to 1.
    # Delete the old chunks, then re-chunk and re-embed the new text as fresh rows.
    _collection.delete(ids=existing_ids)
    ids, chunks, metadatas = _build_chunk_rows(document_id, body.document_text, body.category, tags_str)
    _collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)

    return {
        "document_id": document_id,
        "chunk_count": len(chunks),
        "message": f"Document re-embedded and re-indexed as {len(chunks)} chunk(s).",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }


# ── DELETE /api/v1/detective/knowledge/{documentId} ───────────────────────
# Permanently removes a document from the vector store.
# Admin only. Excluded from search results immediately.

@app.delete("/api/v1/detective/knowledge/{document_id}")
def delete_knowledge_document(
    document_id: str,
    authorization: str = Header(default=None)
):
    require_scope(authorization, "write:knowledge")

    # Check it exists first
    existing_ids = _existing_chunk_ids(document_id)
    if not existing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found"
        )

    # Delete permanently — no soft delete, spec says immediately excluded.
    # Deletes every chunk row for this document, not just one.
    _collection.delete(ids=existing_ids)  # gone for good — no undo

    return {
        "document_id": document_id,
        "message": "Document permanently removed from vector store.",
        "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }