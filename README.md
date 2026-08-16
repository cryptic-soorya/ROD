# ROD — Retail Operations Detective

ROD is an AI-powered retail operations investigation system designed to detect, investigate, and explain operational anomalies across sales, inventory, supplier performance, returns, promotions, customer complaints, and product listing changes.

The platform combines a FastAPI backend, a React frontend, a LangGraph-based reasoning agent, MCP tool integrations, and a vector-powered knowledge base to support autonomous investigation workflows and human-readable root-cause analysis.

---

## Overview

ROD helps teams answer questions such as:

- Why are sales dropping in a specific region?
- Which supplier issue is causing delays or stockouts?
- Is a product return spike linked to a recent listing change or customer complaint pattern?
- What evidence supports a suspected operational anomaly?

The system follows an agentic workflow:
1. A user submits an investigation request.
2. The agent gathers evidence from operational tools and structured data sources.
3. It reasons over the evidence using a LangGraph agent loop.
4. It assembles a report with findings, supporting evidence, and confidence.

---

## Key Features

- Agentic investigation workflow using LangGraph
- FastAPI backend for investigation, auth, report, and knowledge APIs
- React + Vite frontend for interactive investigations
- MCP-backed tool layer for operational data access
- Retrieval-augmented generation (RAG) using pgvector and embeddings
- Knowledge base ingestion and semantic search
- Structured report generation and export support
- JWT-based authentication and scoped access control
- Postgres-backed data layer with seeded retail domain datasets

---

## Architecture

The project is split into a backend service and a frontend app.

### Backend
The backend lives under the `rod/` directory and includes:

- `main.py` — FastAPI application entry point
- `agent/` — agent reasoning, tool orchestration, prompts, and report generation
- `mcp_server/` — MCP tool server and tool implementations
- `knowledge_base/` — document ingestion, chunking, embedding, and vector search
- `auth/` — login, refresh, token management, and authorization
- `investigations/` — investigation lifecycle and request handling
- `reports/` — report generation and export
- `seeds/` — sample retail data and anomaly seed scripts
- `tests/` — validation and regression tests

### Frontend
The frontend lives under `frontend/` and provides the UI for:

- login and authentication
- investigation creation
- investigation history and detail views
- knowledge admin tools
- report display and capabilities pages

---

## Tech Stack

### Backend
- Python
- FastAPI
- PostgreSQL
- pgvector
- LangGraph
- LangChain
- sentence-transformers
- FastMCP
- PyJWT
- ReportLab
- pytest

### Frontend
- React
- TypeScript
- Vite
- React Router

---

