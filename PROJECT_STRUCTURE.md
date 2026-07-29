# ROD — Retail Operations Detective
## Project Structure & Team Ownership Guide

> Last synced to actual code: 2026-07-28. This replaces the original June-2026
> planning version of this doc — that version described the intended
> architecture before the Postgres migration and LangGraph rewrite; this one
> describes what's actually in the repo now.

---

## Why This Document Exists

Merge conflicts happen when two people edit the same file without knowing it.
This doc solves that by:
1. Showing every file that currently exists in this project
2. Marking who owns what with `← NAME`
3. Explaining why each file exists so nobody accidentally duplicates work

This file is duplicated at the repo root (`/Users/soorya/litmus/PROJECT_STRUCTURE.md`)
and here in `rod/`. Keep both in sync when you edit it.

---

## Full Folder Structure

```
litmus/
├── run-dev.sh                            # starts backend (:8000) + frontend (:5173) together
├── PROJECT_STRUCTURE.md                  # this file
├── frontend/                             # React 19 + Vite + TypeScript + react-router-dom
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
│
└── rod/                                  # ── the actual backend project ──
    │
    ├── .env                              # never commit this (gitignored)
    ├── .gitignore                        # ignores: .env, __pycache__, *.pyc, *.db, venv/
    ├── requirements.txt                  # every pip dependency pinned with versions
    ├── main.py                           # FastAPI app — mounts all routers, opens db_pool, starts server
    ├── db_pool.py                        # shared psycopg2 ThreadedConnectionPool per DSN, stale-connection
    │                                     # revalidation (see CLAUDE.md's Database section)
    ├── logging_config.py                 # get_logger() — structured logging used across every module
    ├── run.sh                            # one-off migration helper (finds generate_token() call sites) —
    │                                     # NOT the app launcher, despite the name
    │
    ├── auth/                             # ── Authentication & Authorization ──
    │   ├── __init__.py
    │   ├── jwt_handler.py                # generate_user_token(), generate_agent_token(), verify_token(),
    │   │                                 # check_scope()
    │   ├── models.py                     # LoginRequest, LoginResponse, UserPublic pydantic models
    │   ├── router.py                     # POST /auth/login, /auth/refresh, /auth/logout; ROLE_SCOPES table
    │   ├── user_store.py                 # rod_auth.user (Postgres) — get_user_by_username/id,
    │   │                                 # verify_password (sha256, not bcrypt)
    │   └── refresh_token.py              # refresh token storage/rotation, reuse detection
    │
    ├── investigations/                   # ── Investigation Session Management (HTTP) ──
    │   ├── __init__.py
    │   ├── models.py                     # Investigation, InvestigationStatus, AnomalyCategory, Report models
    │   ├── router.py                     # POST /investigate, GET /investigation/{id}, GET /investigations —
    │   │                                 # eid-scoped for managers, 404-not-403 on other users' records
    │   ├── service.py                    # Postgres queue/status logic (psycopg2, via db_pool)
    │   └── orchestration.db              # STALE local SQLite artifact — gitignored, not read by live code
    │
    ├── agent/                            # ── LangGraph Reasoning Engine ──
    │   ├── __init__.py
    │   ├── graph.py                      # the StateGraph itself: agent → tools → agent loop, finalize node.
    │   │                                 # Same termination contract the old react_loop.py had (max 10 turns,
    │   │                                 # text-only turn = final answer, exhaustion = forced 0.0 confidence)
    │   ├── tools.py                      # wraps mcp_server/tools/*.py functions for LangGraph tool-calling
    │   ├── orchestrator.py               # persistence/report-compilation glue — investigations/router.py's
    │   │                                 # background task entry point; calls graph.run_investigation() then
    │   │                                 # writes Report + FRS report dict
    │   ├── report_parsing.py             # shared JSON-report parser (extracted from the old react_loop.py)
    │   ├── classifier.py                 # anomaly category classification
    │   ├── confidence.py                 # score check + escalation trigger (<0.7 → escalated)
    │   ├── grounding.py                  # evidence-grounding helper
    │   └── prompts.py                    # system prompt + tool descriptions sent to Gemini
    │
    ├── mcp_server/                       # ── MCP Tools (standalone stdio server + shared tool functions) ──
    │   ├── __init__.py
    │   ├── server.py                     # FastMCP server — registers every tool for EXTERNAL MCP clients only.
    │   │                                 # The live agent path (agent/tools.py) calls these functions
    │   │                                 # in-process; this file/process is never spawned by an investigation.
    │   ├── auth_middleware.py            # startup_check() + check_scope() per tool call
    │   │
    │   ├── tools/
    │   │   ├── __init__.py
    │   │   ├── sales.py                  # get_sales_data, get_stores_with_sales_decline,
    │   │   │                             # get_stores_with_sku_decline  → sales schema (Postgres)
    │   │   ├── inventory.py              # get_inventory_levels, get_replenishment_history → inventory schema
    │   │   ├── returns.py                # get_return_reasons, get_product_listing_changes → returns schema
    │   │   ├── customers.py              # get_customer_complaints → customers schema
    │   │   ├── promotions.py             # get_promotion_performance → promotions schema
    │   │   ├── suppliers.py              # get_delivery_performance → suppliers schema        ← SOORYA
    │   │   └── knowledge.py              # knowledge_search → Postgres knowledge.chunks (pgvector)     ← SOORYA
    │   │
    │   └── db/                           # STALE local SQLite files — gitignored (*.db), not used by the
    │       ├── sales.db                  # live code path anymore. Everything above reads Postgres via
    │       ├── inventory.db              # db_pool.py now. Kept around locally; safe to ignore/delete.
    │       ├── returns.db
    │       ├── customers.db
    │       ├── promotions.db
    │       ├── suppliers.db
    │       └── rod.db
    │
    ├── knowledge_base/                   # ── Agentic RAG Knowledge Base ──                    ← SOORYA
    │   ├── __init__.py
    │   ├── pg_vector_client.py            # Postgres+pgvector store factory, table: knowledge.chunks
    │   │                                 # (shared Supabase DB — replaced chroma_client.py 2026-07-28)
    │   ├── chunking.py                   # document chunking for embedding
    │   ├── embedder.py                   # all-MiniLM-L6-v2 local embedding wrapper (sentence-transformers
    │   │                                 # directly now, not via chromadb's wrapper)
    │   ├── router.py                     # standalone FastAPI `app`: POST/PUT/DELETE
    │   │                                 # /api/v1/detective/knowledge — mounted into main.py's app, not
    │   │                                 # run as its own uvicorn process despite the docstring
    │   └── service.py                    # add/update/delete doc + immediate reindex logic
    │
    ├── reports/                          # ── Evidence Trail & Report Generation ──
    │   ├── __init__.py
    │   ├── generator.py                  # compile_report() — evidence trail → structured FRS JSON report
    │   ├── service.py                    # Postgres persistence — save_report, get_latest_report
    │   ├── router.py                     # GET /report/{id}, GET /report/{id}/export?format=pdf|json —
    │   │                                 # admin sees all, manager sees only their own (eid-scoped, 404 not 403)
    │   └── exporter.py                   # PDF export (reportlab) + JSON export
    │
    ├── seeds/                            # seed scripts — Postgres unless noted otherwise
    │   ├── __init__.py
    │   ├── db.py                         # shared Postgres connection helper (get_conn, bulk_insert,
    │   │                                 # fetch_ids) — replaces the old per-file sqlite3.connect() pattern
    │   ├── seed_reference.py             # auth.user + reference.* — run first, everything else depends on it
    │   ├── seed_sales.py
    │   ├── seed_inventory.py
    │   ├── seed_returns.py
    │   ├── seed_customers.py
    │   ├── seed_promotions.py
    │   ├── seed_suppliers.py                                                                  ← SOORYA
    │   ├── seed_orchestration.py         # catalog_changes, needs reference.sku
    │   ├── seed_knowledge.py             # Postgres/pgvector — separate from seed_all.py, run on its own    ← SOORYA
    │   ├── seed_all.py                   # runs the domain seeds in FK-safe order — check its SCRIPTS list,
    │   │                                 # some entries are currently commented out
    │   ├── seed_anomaly.py               # supplier_delay anomaly — Postgres-migrated, known good
    │   ├── seed_anomaly_returns.py       # return_surge anomaly — STILL sqlite3, not yet ported
    │   ├── seed_anomaly_customer.py      # customer_complaint anomaly — STILL sqlite3, not yet ported
    │   ├── seed_anomaly_promotion.py     # promotion_underperform anomaly — STILL sqlite3, not yet ported
    │   ├── wipe_data.py                  # truncate/reset helper
    │   └── refresh.py                    # re-seed helper
    │
    ├── scripts/
    │   ├── mint_token.py                 # mints a MCP_AUTH_TOKEN / user token from the CLI for local testing
    │   └── show_evidence.py              # debug helper to dump an investigation's evidence trail — STILL
    │                                     # sqlite3, not yet ported to Postgres
    │
    └── tests/                            # one test_*.py per module; conftest.py loads .env for pytest
        ├── conftest.py
        ├── test_authmiddleware.py
        ├── test_classifier.py
        ├── test_graph.py                 # covers agent/graph.py (LangGraph engine)
        ├── test_mcp_tools.py
        ├── test_orchestrator.py
        ├── test_report_parsing.py
        ├── test_report.py
        ├── test_seeds.py                 # STILL exercises the sqlite3-based seed scripts
        ├── test_agent.py                 # empty placeholder
        ├── test_auth.py                  # empty placeholder
        ├── test_investigations.py        # empty placeholder
        └── test_knowledge_base.py        # empty placeholder
```

---

## Team Ownership Map

> Rule: if your name is on a file, you are the only one who edits it unless you announce it first.

| File / Folder | Owner | Status |
|---|---|---|
| `mcp_server/tools/suppliers.py` | **Soorya** | ✅ Done, Postgres |
| `mcp_server/tools/knowledge.py` | **Soorya** | ✅ Done |
| `knowledge_base/` (entire folder) | **Soorya** | ✅ Done |
| `seeds/seed_suppliers.py` | **Soorya** | ✅ Done |
| `seeds/seed_knowledge.py` | **Soorya** | ✅ Done |
| `auth/` (entire folder) | Teammate A | maintained |
| `investigations/` (entire folder) | Teammate B | maintained |
| `agent/` (entire folder) | Teammate C | maintained — LangGraph migration merged |
| `mcp_server/tools/sales.py`, `inventory.py`, `returns.py`, `customers.py`, `promotions.py` | Teammate D | maintained |
| `reports/` (entire folder) | Teammate E | maintained |
| `main.py`, `requirements.txt`, `mcp_server/server.py`, `mcp_server/auth_middleware.py`, `db_pool.py` | Team Lead | maintained |
| `frontend/` (entire folder) | — | see repo for current owner |

---

## Module Map (Who Talks to Whom)

```
Human / Frontend (React, :5173)
        │
        ▼
    main.py  (FastAPI, :8000) ───────────────────────────────────────┐
        │                                                            │
        ▼                                                            ▼
   auth/router.py                                       investigations/router.py
   (login/refresh/logout)                        (POST /investigate, GET /investigation(s))
        │                                                            │
        ▼                                                            ▼
  auth/jwt_handler.py                            investigations/service.py (Postgres)
  auth/user_store.py (Postgres)                                      │
                                                                      ▼
                                                          agent/orchestrator.py
                                                          (background task)
                                                                      │
                                                                      ▼
                                                             agent/graph.py
                                                    (LangGraph: agent → tools → agent, ×10 max)
                                                            │              │
                                              ┌─────────────┘              └──────────────┐
                                              ▼                                           ▼
                                       agent/tools.py                     knowledge_base/pg_vector_client.py
                              (calls mcp_server/tools/*.py                (Postgres/pgvector semantic search)
                                   in-process — no subprocess)
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                       Postgres (Supabase) — one DB, per-domain schemas        knowledge.chunks
                       sales / inventory / returns / customers /               (Postgres/pgvector, same DB)
                       promotions / suppliers / rod_auth / investigations
                              │
                              ▼
                     agent/orchestrator.py → reports/generator.py
                     (compile evidence trail → FRS JSON report, Postgres via reports/service.py)
                              │
                              ▼
                     reports/router.py
                     (GET /report/{id} + PDF export — eid-scoped for managers)
```

`mcp_server/server.py` (FastMCP, stdio) is a **separate, optional** process for external MCP
clients (e.g. Claude Desktop) — it is not part of the path above and is never spawned by an
investigation.

---

## The Server(s) Running

### Backend — FastAPI HTTP Server (`main.py`)
- Runs on **port 8000** via `run-dev.sh` / `uvicorn main:app --reload --port 8000` (some older
  docstrings in the code still say 8001 — that's stale, 8000 is what `run-dev.sh` actually binds)
- Handles: login, start/status/list investigations, knowledge CRUD, get/export report
- What the frontend talks to

### Frontend — Vite dev server (`frontend/`)
- Runs on **port 5173**
- `FRONTEND_ORIGIN` env var on the backend must match this for CORS + the httpOnly refresh cookie to work

### Optional — FastMCP stdio server (`mcp_server/server.py`)
- Runs on stdio (not a port — it's a pipe)
- For external MCP clients only; the live agent does **not** use this process
- Start manually: `python -m mcp_server.server`

---

## JWT Flow (Plain English)

1. Human hits `POST /auth/login` → gets a JWT with scopes from `ROLE_SCOPES[role]`, plus `store_id`
   as a claim if they're a manager
2. Human includes that JWT in every subsequent request header: `Authorization: Bearer <token>`
3. A separate **agent service token** (`MCP_AUTH_TOKEN`, minted via `generate_agent_token()`) is
   what the agent's tool calls authenticate with — independent of any human session
4. `mcp_server/auth_middleware.py`'s `startup_check()` validates `MCP_AUTH_TOKEN` once at app
   startup; refuses to start if missing/expired
5. Every single tool call checks scope **again** before touching any database (`check_scope()`)

**Why twice?** Startup check = "is this session valid at all?". Per-call check = "does this
specific tool call have permission?".

---

## Scope → Schema → Tool Mapping (Quick Reference)

| JWT Scope | Postgres schema | Tools That Need It |
|---|---|---|
| `read:sales` | `sales` | `get_sales_data`, `get_stores_with_sales_decline`, `get_stores_with_sku_decline` |
| `read:inventory` | `inventory` | `get_inventory_levels`, `get_replenishment_history` |
| `read:returns` | `returns` | `get_return_reasons`, `get_product_listing_changes` |
| `read:customers` | `customers` | `get_customer_complaints` |
| `read:promotions` | `promotions` | `get_promotion_performance` |
| `read:suppliers` | `suppliers` | `get_delivery_performance` |
| `read:knowledge` | `knowledge` (Postgres/pgvector) | `knowledge_search` |
| `write:knowledge` | `knowledge` (Postgres/pgvector) | POST/PUT/DELETE `/knowledge` endpoints |
| `read:reports` | `investigations`/`reports` | GET `/report(s)`, GET `/investigation(s)` — enforced (eid-scoped for managers) |

See `CLAUDE.md`'s Role → scope table for which roles get which scopes — it changed 2026-07-27
(`category_manager`/`store_manager` collapsed into one `manager` role with a different scope set).

---

## Critical Implementation Rules (Do Not Break These)

| Rule | Detail |
|---|---|
| `degradation_flag` trigger | `avg_delivery_days_current > 1.5 × avg_delivery_days_baseline` |
| Knowledge similarity score formula | `1 - cosine_distance` (pgvector `<=>` operator, HNSW `vector_cosine_ops` index) |
| `knowledge_search` must respond within | **500ms** — local embeddings only, no external API |
| Tool failures must return | **structured error dict** — never raise exceptions |
| JWT scope checked | **twice**: server startup + per tool call |
| MCP standalone-server transport | **stdio** only (not used by the live agent path) |
| Knowledge table name | `knowledge.chunks` (Postgres/pgvector, was Chroma collection `retail_kb`) |
| Knowledge metadata fields | `category` (SOP or Past Case), `tags` (comma-separated string) |
| Agent confidence threshold | `≥ 0.7` → completed; `< 0.7` → escalated |
| Max agent iterations | **10** hard cap (`agent/graph.py`) |
| Reports are | **immutable** — no PUT/PATCH on report content |
| Investigation/report ownership | manager sees only their own (eid-scoped); missing/other's record → 404, never 403 |
| Password hashing | **sha256**, not bcrypt, despite `bcrypt` being pinned in `requirements.txt` |

---

## Environment Variables (`.env`)

See `CLAUDE.md`'s Environment Variables section for the full current list (Postgres DSNs,
Gemini keys, JWT secrets, etc). There is currently no checked-in `.env.example` — don't assume
one exists.

---

## Setup Instructions (Run in This Order)

```bash
# 1. Clone repo, create venv at repo root
python3.12 -m venv venv
source venv/bin/activate

# 2. Install backend deps
cd rod && pip install -r requirements.txt

# 3. Install frontend deps
cd ../frontend && npm install

# 4. Fill in rod/.env — see CLAUDE.md for the full var list (DATABASE_URL, JWT_SECRET,
#    GEMINI_API_KEY_1..5, etc). No .env.example to copy from currently.

# 5. Make sure the Postgres DB exists (Supabase project, or local `createdb rod_db`),
#    then seed it:
cd rod
python seeds/seed_reference.py
python seeds/seed_all.py         # check SCRIPTS list inside — some entries commented out
python seeds/seed_knowledge.py   # Postgres/pgvector, separate from seed_all.py — seeds the shared team DB
python seeds/seed_anomaly.py     # optional, Postgres-migrated engineered anomaly

# 6. Start both servers together from repo root
cd ..
./run-dev.sh
# backend: http://localhost:8000   frontend: http://localhost:5173
```

---

## What's Already Done (Soorya's Modules)

| Component | File | What It Does |
|---|---|---|
| Delivery performance MCP tool | `mcp_server/tools/suppliers.py` | Queries `suppliers` schema (Postgres), returns `avg_delivery_days_current`, `avg_delivery_days_baseline`, `defect_rate`, `degradation_flag` |
| Knowledge search MCP tool | `mcp_server/tools/knowledge.py` | Semantic search over Postgres/pgvector `knowledge.chunks` table using `all-MiniLM-L6-v2` |
| Suppliers seed | `seeds/seed_suppliers.py` | Pre-seeded supplier delivery data (Postgres) |
| Knowledge base + seed | `knowledge_base/pg_vector_client.py` + `seeds/seed_knowledge.py` | Shared Supabase-backed SOPs and Past Cases |
| Knowledge CRUD API | `knowledge_base/router.py` + `knowledge_base/service.py` | POST/PUT/DELETE `/api/v1/detective/knowledge` — Admin only, `write:knowledge` scope |

---

## Quick Sanity Check Commands

```bash
# Test MCP tools (includes suppliers + knowledge)
python -m pytest tests/test_mcp_tools.py -v

# Test the LangGraph agent engine
python -m pytest tests/test_graph.py -v

# Test the orchestrator (persistence/report-compilation glue)
python -m pytest tests/test_orchestrator.py -v

# Run all tests
python -m pytest tests/ -v
```

Note: `test_auth.py`, `test_agent.py`, `test_investigations.py`, and `test_knowledge_base.py`
are currently empty placeholders — don't rely on them for coverage of those modules.

---

*Document version: 2.0 — 2026-07-28 | rewritten to match actual code after the Postgres +
LangGraph migrations. Update this file whenever the structure changes — don't let it go stale
again.*
