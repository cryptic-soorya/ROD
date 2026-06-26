# ROD — Retail Operations Detective
## Project Structure & Team Ownership Guide

> Push this file into the `dev/` folder on GitHub.  
> Every teammate reads this before touching a single file.

---

## Why This Document Exists

Merge conflicts happen when two people edit the same file without knowing it.  
This doc solves that by:
1. Showing **every file** that will ever exist in this project
2. Marking **who owns what** with `← NAME`
3. Explaining **why each file exists** so nobody accidentally duplicates work

---

## Full Folder Structure

```
rod/
│
├── .env.example                          # ENV variable template (never commit .env itself)
├── .gitignore                            # ignores: .env, __pycache__, *.db, chroma_db/, venv/
├── README.md                             # project overview + quickstart for new teammates
├── CLAUDE.md                             # context file for Claude Code AI sessions
├── PLAN.md                               # full team plan, DB schemas, integration checklist
├── requirements.txt                      # every pip dependency pinned with versions
├── main.py                               # FastAPI app — mounts all routers, starts server
│
├── auth/                                 # ── MODULE 1: Authentication & Authorization ──
│   ├── __init__.py
│   ├── jwt_handler.py                    # generate_token(), verify_token(), check_scope()
│   ├── models.py                         # User pydantic model
│   └── router.py                         # POST /auth/login endpoint
│
├── investigations/                       # ── MODULE 2 (HTTP side): Session Management ──
│   ├── __init__.py
│   ├── models.py                         # Investigation, ToolCall, Report pydantic models
│   ├── router.py                         # POST /investigate, GET /investigation/{id}, GET /investigations
│   ├── service.py                        # queue logic, status updates, pagination
│   └── orchestration.db                  # SQLite: users, investigations, tool_calls, reports, audit_logs
│
├── agent/                                # ── MODULE 4: ReAct Reasoning Engine ──
│   ├── __init__.py
│   ├── react_loop.py                     # core loop: Thought → Action → Observation (max 10)
│   ├── classifier.py                     # anomaly category classification (emergent, not hardcoded)
│   ├── confidence.py                     # score check + escalation trigger (<0.7 → escalated)
│   └── prompts.py                        # system prompt + tool descriptions sent to Claude Sonnet
│
├── mcp_server/                           # ── MODULE 2 (MCP side): All 9 MCP Tools ──
│   ├── __init__.py
│   ├── server.py                         # FastMCP server: tool registration + stdio transport
│   ├── auth_middleware.py                # startup token validation + per-call check_scope()
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── sales.py                      # TOOL 1 — get_sales_data          → sales.db
│   │   ├── inventory.py                  # TOOL 2 — get_inventory_levels     → inventory.db
│   │   │                                 # TOOL 3 — get_replenishment_history→ inventory.db
│   │   ├── returns.py                    # TOOL 4 — get_return_reasons       → returns.db
│   │   │                                 # TOOL 5 — get_product_listing_changes→ returns.db
│   │   ├── customers.py                  # TOOL 6 — get_customer_complaints  → customers.db
│   │   ├── promotions.py                 # TOOL 7 — get_promotion_performance→ promotions.db
│   │   ├── suppliers.py                  # TOOL 8 — get_delivery_performance → suppliers.db   ← SOORYA
│   │   └── knowledge.py                  # TOOL 9 — knowledge_search         → chroma_db/     ← SOORYA
│   │
│   └── db/                               # domain SQLite databases live here
│       ├── sales.db
│       ├── inventory.db
│       ├── returns.db
│       ├── customers.db
│       ├── promotions.db
│       └── suppliers.db                  # ← SOORYA owns this file + its seed script
│
├── knowledge_base/                       # ── MODULE 3: Agentic RAG Knowledge Base ──
│   ├── __init__.py
│   ├── chroma_client.py                  # ChromaDB init, collection name: retail_kb            ← SOORYA
│   ├── embedder.py                       # all-MiniLM-L6-v2 local embedding wrapper             ← SOORYA
│   ├── router.py                         # FastAPI: POST/PUT/DELETE /api/v1/detective/knowledge  ← SOORYA
│   ├── service.py                        # add/update/delete doc + immediate reindex logic       ← SOORYA
│   └── chroma_db/                        # persisted ChromaDB vector store (in .gitignore)       ← SOORYA
│
├── reports/                              # ── MODULE 5: Evidence Trail & Report Generation ──
│   ├── __init__.py
│   ├── generator.py                      # internal: evidence trail → structured JSON report
│   ├── router.py                         # GET /report/{id} and GET /report/{id}/export
│   └── exporter.py                       # PDF export logic (reportlab)
│
├── seeds/                                # seed scripts — run once to populate each DB
│   ├── seed_sales.py
│   ├── seed_inventory.py
│   ├── seed_returns.py
│   ├── seed_customers.py
│   ├── seed_promotions.py
│   ├── seed_suppliers.py                 # ← SOORYA (DONE ✓)
│   └── seed_knowledge.py                # ← SOORYA (DONE ✓)
│
└── tests/                                # one test file per module
    ├── test_auth.py
    ├── test_investigations.py
    ├── test_agent.py
    ├── test_mcp_tools.py
    ├── test_knowledge_base.py
    └── test_reports.py
```

---

## Team Ownership Map

> **Rule: if your name is on a file, you are the only one who edits it unless you announce it in the group chat first.**

| File / Folder | Owner | Status |
|---|---|---|
| `mcp_server/tools/suppliers.py` | **Soorya** | ✅ Done |
| `mcp_server/tools/knowledge.py` | **Soorya** | ✅ Done |
| `mcp_server/db/suppliers.db` | **Soorya** | ✅ Done |
| `knowledge_base/` (entire folder) | **Soorya** | ✅ Done |
| `seeds/seed_suppliers.py` | **Soorya** | ✅ Done |
| `seeds/seed_knowledge.py` | **Soorya** | ✅ Done |
| `auth/` (entire folder) | Teammate A | — |
| `investigations/` (entire folder) | Teammate B | — |
| `agent/` (entire folder) | Teammate C | — |
| `mcp_server/tools/sales.py` | Teammate D | — |
| `mcp_server/tools/inventory.py` | Teammate D | — |
| `mcp_server/tools/returns.py` | Teammate D | — |
| `mcp_server/tools/customers.py` | Teammate D | — |
| `mcp_server/tools/promotions.py` | Teammate D | — |
| `reports/` (entire folder) | Teammate E | — |
| `main.py` | **Team Lead** | — |
| `requirements.txt` | **Team Lead** | — |
| `mcp_server/server.py` | **Team Lead** | — |
| `mcp_server/auth_middleware.py` | **Team Lead** | — |

> Replace "Teammate A/B/C/D/E" with real names and assign in your group chat.

---

## Module Map (Who Talks to Whom)

```
User / Monitoring Job
        │
        ▼
    main.py  ──────────────────────────────────────────────┐
        │                                                   │
        ▼                                                   ▼
   auth/router.py                              investigations/router.py
   (POST /auth/login)                    (POST /investigate, GET /investigation/...)
        │                                                   │
        ▼                                                   ▼
  auth/jwt_handler.py               investigations/service.py
  (generate + verify JWT)                (queue + status logic)
                                                   │
                                                   ▼
                                          agent/react_loop.py
                                    (Thought → Action → Observation × 10)
                                          │              │
                              ┌───────────┘              └──────────────┐
                              ▼                                         ▼
                   mcp_server/server.py                    knowledge_base/chroma_client.py
                   (9 MCP tools via stdio)                 (ChromaDB semantic search)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
          sales.db      suppliers.db     retail_kb
          returns.db    inventory.db     (ChromaDB)
          customers.db  promotions.db
                              │
                              ▼
                     reports/generator.py
                     (compile evidence trail → JSON report)
                              │
                              ▼
                     reports/router.py
                     (GET /report/{id} + PDF export)
```

---

## The Two Servers Running Simultaneously

This is the part that trips people up. There are **two separate processes** running at the same time:

### Server 1 — FastAPI HTTP Server (`main.py`)
- Runs on **port 8001** via uvicorn
- Handles: login, start/status/list investigations, knowledge CRUD, get/export report
- What humans and the frontend talk to
- Start: `uvicorn main:app --port 8001 --reload`

### Server 2 — FastMCP MCP Server (`mcp_server/server.py`)
- Runs on **stdio** (not a port — it's a pipe)
- Handles: all 9 tool calls made by the ReAct agent
- What the agent talks to internally
- Start: `python mcp_server/server.py` (the agent spawns this as a subprocess)

**They are not the same server. Do not confuse them.**

---

## JWT Flow (Plain English)

1. Human hits `POST /auth/login` → gets a JWT valid 60 min
2. Human includes that JWT in every subsequent request header: `Authorization: Bearer <token>`
3. When agent starts, `generate_token()` creates a **second** JWT (agent service token) — max 30 min
4. That agent token goes into env var `MCP_AUTH_TOKEN`
5. MCP server reads `MCP_AUTH_TOKEN` at startup — refuses to start if missing/expired
6. Every single tool call checks scope **again** before touching any DB

**Why twice?** Startup check = "is this session valid at all?". Per-call check = "does this specific tool call have permission?". Belt AND suspenders.

---

## Scope → DB → Tool Mapping (Quick Reference)

| JWT Scope | Database | Tools That Need It |
|---|---|---|
| `read:sales` | `sales.db` | `get_sales_data` |
| `read:inventory` | `inventory.db` | `get_inventory_levels`, `get_replenishment_history` |
| `read:returns` | `returns.db` | `get_return_reasons`, `get_product_listing_changes` |
| `read:customers` | `customers.db` | `get_customer_complaints` |
| `read:promotions` | `promotions.db` | `get_promotion_performance` |
| `read:suppliers` | `suppliers.db` | `get_delivery_performance` |
| `read:knowledge` | `chroma_db/` | `knowledge_search` |
| `write:knowledge` | `chroma_db/` | POST/PUT/DELETE `/knowledge` endpoints |
| `admin:investigations` | `orchestration.db` | view all investigations |

---

## Critical Implementation Rules (Do Not Break These)

These are already decided. Do not re-debate them. If you disagree, raise it in group chat before changing anything.

| Rule | Detail |
|---|---|
| `degradation_flag` trigger | `avg_delivery_days_current > 1.5 × avg_delivery_days_baseline` |
| ChromaDB similarity score formula | `1 / (1 + l2_distance)` |
| `knowledge_search` must respond within | **500ms** — local embeddings only, no external API |
| Tool failures must return | **structured error dict** — never raise exceptions |
| JWT scope checked | **twice**: server startup + per tool call |
| MCP transport | **stdio** only |
| ChromaDB collection name | `retail_kb` |
| ChromaDB metadata fields | `category` (SOP or Past Case), `tags` (comma-separated string) |
| Agent confidence threshold | `≥ 0.7` → completed; `< 0.7` → escalated |
| Max ReAct iterations | **10** hard cap |
| Agent token max expiry | **30 minutes** |
| Reports are | **immutable** — no PUT/PATCH on report content |

---

## Environment Variables (`.env`)

```bash
# Copy this to .env and fill in values. NEVER commit .env to git.

JWT_SECRET=your-super-secret-key-here
MCP_AUTH_TOKEN=                         # auto-generated at runtime by auth/jwt_handler.py
ANTHROPIC_API_KEY=your-anthropic-key
DB_PATH=./mcp_server/db/               # path to all .db files
CHROMA_PATH=./knowledge_base/chroma_db/
KNOWLEDGE_SAMPLE_MIN=10                 # low_sample_warning threshold for get_return_reasons
```

---

## Git Branch Strategy (Prevent Merge Conflicts)

```
main
 └── dev                    ← everyone branches from here, PRs go back here
      ├── feat/auth          ← Teammate A
      ├── feat/investigations← Teammate B
      ├── feat/agent         ← Teammate C
      ├── feat/mcp-tools     ← Teammate D
      ├── feat/reports       ← Teammate E
      └── feat/soorya        ← Soorya (already done, can be merged first)
```

**Rules:**
1. Never commit directly to `main` or `dev`
2. Branch name must match the module you own
3. One PR per feature — no bundling unrelated files
4. Before merging: `git pull origin dev` into your branch first to catch conflicts locally

---

## Setup Instructions (Run in This Order)

```bash
# 1. Clone repo
git clone <repo-url>
cd rod

# 2. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate          # Mac/Linux
# venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and fill environment variables
cp .env.example .env
# edit .env with your JWT_SECRET and ANTHROPIC_API_KEY

# 5. Run seed scripts (one per domain DB)
python seeds/seed_suppliers.py
python seeds/seed_knowledge.py
python seeds/seed_sales.py
# ... etc for each domain

# 6. Start FastAPI server
uvicorn main:app --port 8001 --reload

# 7. MCP server starts automatically when an investigation is triggered
#    (agent/react_loop.py spawns it as a subprocess)
```

---

## What's Already Done (Soorya's Modules)

| Component | File | What It Does |
|---|---|---|
| Delivery performance MCP tool | `mcp_server/tools/suppliers.py` | Queries `suppliers.db`, returns `avg_delivery_days_current`, `avg_delivery_days_baseline`, `defect_rate`, `degradation_flag` |
| Knowledge search MCP tool | `mcp_server/tools/knowledge.py` | Semantic search over ChromaDB `retail_kb` collection using `all-MiniLM-L6-v2` |
| Suppliers database + seed | `mcp_server/db/suppliers.db` + `seeds/seed_suppliers.py` | Pre-seeded supplier delivery data |
| ChromaDB + seed | `knowledge_base/chroma_db/` + `seeds/seed_knowledge.py` | Pre-seeded SOPs and Past Cases |
| Knowledge CRUD API | `knowledge_base/router.py` + `knowledge_base/service.py` | POST/PUT/DELETE `/api/v1/detective/knowledge` — Admin only, `write:knowledge` scope |

**Soorya's modules are self-contained. They do not depend on any other teammate's incomplete work.**

---

## Quick Sanity Check Commands

Run these to verify your module works before raising a PR:

```bash
# Test JWT generation and scope check
python -m pytest tests/test_auth.py -v

# Test MCP tools (includes suppliers + knowledge)
python -m pytest tests/test_mcp_tools.py -v

# Test knowledge base CRUD
python -m pytest tests/test_knowledge_base.py -v

# Test full investigation flow (needs all modules)
python -m pytest tests/test_investigations.py -v

# Run all tests
python -m pytest tests/ -v
```

---

*Document version: 1.0 — June 2026 | ROD Team — Litmus7 DFI Intern Team*  
*Update this file if the structure changes. Do not let it go stale.*
