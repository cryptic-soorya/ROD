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
## Prerequisites
Before running the project, make sure you have:

  Python 3.10 or newer
  Node.js 18+ and npm
  PostgreSQL database
  pgvector enabled
  Local environment variables configured
  
---
## Environment Configuration

Create a .env file in the rod directory with the required values for your local setup, such as:

        DATABASE_URL=postgresql://user:password@localhost:5432/rod_db
        KNOWLEDGE_DB_URL=postgresql://user:password@localhost:5432/rod_db
        ROD_AUTH_DB_URL=postgresql://user:password@localhost:5432/rod_db
        MCP_AUTH_TOKEN=your_agent_token_here
        FRONTEND_ORIGIN=http://localhost:5173
        
You may also need database-specific URLs depending on your environment setup.

---
## Getting Started

1. Install backend dependencies
   
        cd rod
        python -m venv venv
        source venv/bin/activate   # On Windows: venv\Scripts\activate
        pip install -r requirements.txt
   
3. Install frontend dependencies
   
        cd frontend
        npm install
5. Start the application
You can use the project launcher:

        cd ..
        ./run-dev.sh

This typically starts:

    Backend: http://localhost:8000
    Frontend: http://localhost:5173

Alternatively, run each service manually:
  
    cd rod
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    cd frontend
    npm run dev -- --host 0.0.0.0 --port 5173
  ## Running Tests
  The project uses pytest for backend verification.
  
    cd rod
    pytest

## Typical Workflow
- Seed the database with retail operational data.
- Start the backend and frontend.
- Log in through the UI.
- Create a new investigation describing the anomaly.
- The agent gathers evidence using available tools.
- The system evaluates the evidence, identifies likely root causes, and compiles a report.
- Review findings, confidence, and supporting evidence.

## Use Cases
ROD is designed for retail operations and anomaly detection use cases, including:

- inventory shortages
- supplier delivery issues
- sales declines
- sales declines
- abnormal return patterns
- promotion underperformance
- customer complaint-driven product issues
- product listing or catalog changes affecting performance
  
  --- 
## Notes
This project is intended as an AI-driven operations investigation assistant and is suitable for experimentation, internal tooling, and demo environments. The architecture supports future extension with more domain tools, model benchmarking, and additional investigation workflows.

## License
This project does not currently include a license file. If this project is intended for internal or academic use, add a license before public distribution.

## Contributing
Contributions are welcome for:

  - agent reasoning improvements
  - new operational tools
  - better report generation
  - frontend UX improvements
  - retrieval and knowledge base tuning
  - test coverage and reliability improvements

