"""
seed_orchestrator.py
Creates and seeds the remaining FRS orchestration tables that do NOT already
have a live home elsewhere, into mcp_server/db/orchestrator.db.

Run: python seeds/seed_orchestrator.py

WHY THESE TABLES WERE DROPPED FROM THE ORIGINAL FRS LIST:
- investigations, audit_logs, tool_calls — ALREADY EXIST in
  investigations/orchestration.db, created by Teammate B's actual running
  code (init_investigations_db()). Their real schemas differ substantially
  from the FRS sheet (e.g. investigations.id is INTEGER AUTOINCREMENT with
  a `report` JSON blob column, not the FRS's TEXT id / problem_statement /
  tool_budget shape). The FRS version was aspirational and is superseded —
  do NOT recreate these here, or you get a second disconnected copy that
  the app never actually writes to.
- knowledge_documents, knowledge_chunks — ALREADY HANDLED by ChromaDB
  (seed_knowledge.py populates the real `retail_kb` collection with actual
  sentence-transformer embeddings). A SQL table storing fake JSON
  "embeddings" would be a second, unused, competing system.
- "Investigators" (FRS typo) and "Reccomendations" (duplicate of
  Knowledge_Documents) were already excluded before this — see prior
  conversation for details.

Tables kept here (nothing else in the codebase currently owns them):
    stores, products, sku, agents, kpis, tool_connectors,
    agent_executions, anomalies, hypotheses, root_causes,
    reports, customer_queries

NOTE ON CROSS-DB REFERENCES: investigation_id columns below reference
investigations(id) in investigations/orchestration.db — a different
database file. SQLite cannot enforce foreign keys across separate files,
so these are plain TEXT columns here, not real FKs. Seeded with synthetic
id values (as strings) for testing; they won't correspond to real rows in
orchestration.db unless you cross-reference deliberately.

The `reports` table here is NOT just test seeding — reports/service.py
(save_report / get_latest_report) actively reads and writes this table in
production code, so its schema must not change without updating that file.

Depends on seeds/common.py for PRODUCTS / STORES id lists, reused here so
product_id / store_id values stay consistent with the retail data DBs.
"""
import sqlite3
import os
import random
import json
from datetime import date, timedelta
from common import PRODUCTS, STORES

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "db", "orchestrator.db")
DB_PATH = os.path.abspath(DB_PATH)

random.seed(7)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    id            TEXT PRIMARY KEY,
    store_name    TEXT NOT NULL,
    region        TEXT NOT NULL,
    country       TEXT NOT NULL,
    manager_name  TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id    TEXT PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    brand         TEXT NOT NULL,
    unit_price    REAL NOT NULL,
    status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sku (
    sku_id        TEXT PRIMARY KEY,
    product_id    TEXT NOT NULL REFERENCES products(product_id),
    sku_code      TEXT UNIQUE NOT NULL,
    size          TEXT,
    colour        TEXT,
    stock_quantity INTEGER DEFAULT 0,
    reorder_lvl   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agents (
    id           TEXT PRIMARY KEY,
    agent_name   TEXT NOT NULL,
    agent_type   TEXT NOT NULL,
    description  TEXT,
    capabilities TEXT,
    is_active    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_executions (
    id                TEXT PRIMARY KEY,
    investigation_id  TEXT,   -- FK -> investigations(id) in investigations/orchestration.db (cross-db, not enforced)
    agent_id          TEXT REFERENCES agents(id),
    status            TEXT NOT NULL,
    started_at        DATETIME NOT NULL,
    completed_at       DATETIME,
    output            TEXT
);

CREATE TABLE IF NOT EXISTS kpis (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    unit       TEXT NOT NULL,
    owner_role TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    id                 TEXT PRIMARY KEY,
    investigation_id   TEXT,   -- FK -> investigations(id) in investigations/orchestration.db (cross-db, not enforced)
    kpi_id             TEXT REFERENCES kpis(id),
    expected_value     REAL NOT NULL,
    actual_value       REAL NOT NULL,
    deviation_percent  REAL NOT NULL,
    severity           TEXT NOT NULL,
    detected_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_connectors (
    id             TEXT PRIMARY KEY,
    tool_category  TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    endpoint_url   TEXT NOT NULL,
    input_schema   TEXT,
    is_active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS hypotheses (
    id                 TEXT PRIMARY KEY,
    investigation_id   TEXT,   -- FK -> investigations(id) in investigations/orchestration.db (cross-db, not enforced)
    hypothesis_text    TEXT NOT NULL,
    confidence_score   REAL NOT NULL,
    confidence_band    TEXT NOT NULL,
    uncertainty_note   TEXT,
    rank_no            INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS root_causes (
    id                 TEXT PRIMARY KEY,
    investigation_id   TEXT,   -- FK -> investigations(id) in investigations/orchestration.db (cross-db, not enforced)
    hypothesis_id      TEXT REFERENCES hypotheses(id),
    cause_category     TEXT NOT NULL,
    cause_description  TEXT NOT NULL,
    confidence         REAL NOT NULL
);

-- NOTE: this table is also written to by reports/service.py in production
-- (save_report / get_latest_report). Do not change its shape without
-- updating that file too.
CREATE TABLE IF NOT EXISTS reports (
    id                  TEXT PRIMARY KEY,
    investigation_id    TEXT,   -- FK -> investigations(id) in investigations/orchestration.db (cross-db, not enforced)
    version             INTEGER NOT NULL,
    executive_summary   TEXT NOT NULL,
    report_json         TEXT,
    generated_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_queries (
    query_id          TEXT PRIMARY KEY,
    customer_id       TEXT NOT NULL,
    investigation_id  TEXT,   -- FK -> investigations(id) in investigations/orchestration.db (cross-db, not enforced)
    product_id        TEXT REFERENCES products(product_id),
    query_type        TEXT NOT NULL,
    subject           TEXT NOT NULL,
    description       TEXT NOT NULL,
    priority          TEXT NOT NULL,
    status            TEXT NOT NULL,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at       DATETIME
);
"""

# ── Reference data ─────────────────────────────────────────────────────────

REGIONS = ["Northeast", "Southeast", "Midwest", "West", "South"]
COUNTRIES = ["USA"]
MANAGERS = ["A. Patel", "J. Kim", "M. Rossi", "S. Chen", "D. Okafor", None]

BRANDS = ["Nova", "Everline", "Kestrel", "Bramwell", "Ardent", "Solace"]
CATEGORIES = ["apparel", "footwear", "accessories", "home", "electronics"]

# Synthetic investigation ids — NOT real rows in investigations/orchestration.db.
# investigations.id there is INTEGER AUTOINCREMENT, so these mimic that shape
# as strings (e.g. "1", "2", ...) rather than "inv-0001" style, to read
# consistently with what a real investigation_id would look like.
SYNTHETIC_INVESTIGATION_IDS = [str(i) for i in range(1, 61)]

AGENT_DEFS = [
    ("agent-001", "ReAct Investigator", "react_loop", "Primary autonomous investigation agent", "sql_query,semantic_search,tool_call"),
    ("agent-002", "Confidence Scorer", "confidence", "Scores hypothesis confidence post-loop", "scoring"),
    ("agent-003", "Report Generator", "report_gen", "Compiles final structured report", "summarization"),
]

KPI_DEFS = [
    ("kpi-001", "Units Sold", "sales", "count", "category_manager"),
    ("kpi-002", "Revenue", "sales", "usd", "category_manager"),
    ("kpi-003", "Stock On Hand", "inventory", "count", "store_manager"),
    ("kpi-004", "Return Rate", "returns", "percent", "category_manager"),
    ("kpi-005", "Complaint Volume", "customer", "count", "store_manager"),
    ("kpi-006", "Supplier Delivery Days", "supplier", "days", "admin"),
]

TOOL_CONNECTOR_DEFS = [
    ("tc-001", "sales", "Sales Data Tool", "http://localhost:9001/mcp/sales"),
    ("tc-002", "inventory", "Inventory Data Tool", "http://localhost:9002/mcp/inventory"),
    ("tc-003", "returns", "Returns Data Tool", "http://localhost:9003/mcp/returns"),
    ("tc-004", "suppliers", "Supplier Data Tool", "http://localhost:9004/mcp/suppliers"),
    ("tc-005", "promotions", "Promotions Data Tool", "http://localhost:9005/mcp/promotions"),
    ("tc-006", "knowledge", "Knowledge Base Search", "http://localhost:9006/mcp/knowledge"),
]

HYPOTHESIS_TEMPLATES = [
    "Supplier degradation caused stockouts driving the anomaly",
    "A recent listing/price change explains the deviation",
    "Post-promotion demand collapse is the primary driver",
    "Elevated defect rate correlates with the observed spike",
    "Seasonal demand shift accounts for most of the deviation",
]

CAUSE_CATEGORIES = ["supplier", "pricing", "promotion", "quality", "seasonal", "operational"]

QUERY_TYPES = ["complaint", "return_request", "general_inquiry", "refund_request"]
PRIORITIES = ["low", "medium", "high"]
QUERY_STATUSES = ["open", "in_progress", "resolved", "closed"]


def random_past_date(start_year=2025, start_month=1):
    start = date(start_year, start_month, 1)
    delta = (date(2026, 6, 30) - start).days
    return start + timedelta(days=random.randint(0, delta))


def gen_stores(n=15):
    rows = []
    for store_id in (STORES[:n] if len(STORES) >= n else STORES):
        rows.append((
            store_id,
            f"Store {store_id}",
            random.choice(REGIONS),
            random.choice(COUNTRIES),
            random.choice(MANAGERS),
        ))
    return rows


def gen_products(n=40):
    rows = []
    chosen = PRODUCTS[:n] if len(PRODUCTS) >= n else PRODUCTS
    for product_id in chosen:
        rows.append((
            product_id,
            f"Product {product_id}",
            random.choice(CATEGORIES),
            random.choice(BRANDS),
            round(random.uniform(5, 200), 2),
            random.choice(["active", "discontinued", "seasonal"]),
        ))
    return rows


def gen_sku(product_ids, per_product=2):
    rows = []
    sizes = ["S", "M", "L", "XL", None]
    colours = ["black", "white", "navy", "olive", None]
    for product_id in product_ids:
        for i in range(per_product):
            sku_id = f"sku-{product_id}-{i+1}"
            rows.append((
                sku_id,
                product_id,
                f"{product_id}-{random.choice(colours) or 'std'}-{random.choice(sizes) or 'os'}-{i+1}",
                random.choice(sizes),
                random.choice(colours),
                random.randint(0, 300),
                random.randint(10, 60),
            ))
    return rows


def gen_agent_executions(investigation_ids, agent_ids, per_investigation=1):
    rows = []
    for inv_id in investigation_ids:
        for _ in range(per_investigation):
            exec_id = f"exec-{inv_id}-{random.randint(1000,9999)}"
            started = random_past_date()
            completed = started + timedelta(hours=random.randint(1, 48))
            rows.append((
                exec_id,
                inv_id,
                random.choice(agent_ids),
                random.choice(["completed", "failed", "running"]),
                started.isoformat(),
                completed.isoformat(),
                json.dumps({"summary": "execution output placeholder"}),
            ))
    return rows


def gen_anomalies(investigation_ids, kpi_ids, per_investigation=1):
    rows = []
    for inv_id in investigation_ids:
        for _ in range(per_investigation):
            anomaly_id = f"anom-{inv_id}-{random.randint(1000,9999)}"
            expected = round(random.uniform(100, 1000), 2)
            actual = round(expected * random.uniform(0.3, 1.8), 2)
            deviation = round(((actual - expected) / expected) * 100, 2)
            severity = "high" if abs(deviation) > 40 else ("medium" if abs(deviation) > 15 else "low")
            rows.append((
                anomaly_id,
                inv_id,
                random.choice(kpi_ids),
                expected,
                actual,
                deviation,
                severity,
            ))
    return rows


def gen_hypotheses(investigation_ids, per_investigation=2):
    rows = []
    ids = []
    for inv_id in investigation_ids:
        for rank in range(1, per_investigation + 1):
            hyp_id = f"hyp-{inv_id}-{rank}"
            ids.append((hyp_id, inv_id))
            confidence = round(random.uniform(0.3, 0.95), 2)
            band = "high" if confidence > 0.75 else ("medium" if confidence > 0.5 else "low")
            rows.append((
                hyp_id,
                inv_id,
                random.choice(HYPOTHESIS_TEMPLATES),
                confidence,
                band,
                None if confidence > 0.6 else "Limited sample size in supporting data",
                rank,
            ))
    return rows, ids


def gen_root_causes(hypothesis_pairs):
    rows = []
    for hyp_id, inv_id in hypothesis_pairs:
        if random.random() < 0.6:
            rc_id = f"rc-{hyp_id}"
            rows.append((
                rc_id,
                inv_id,
                hyp_id,
                random.choice(CAUSE_CATEGORIES),
                "Root cause confirmed via cross-referenced tool call evidence",
                round(random.uniform(0.6, 0.98), 2),
            ))
    return rows


def gen_reports(investigation_ids):
    """
    NOTE: reports/service.py already writes real reports here in production
    (with ids like "report-{investigation_id}-v{version}"). These seeded
    rows use a different id pattern ("report-{inv_id}-seed") to avoid ever
    colliding with a real save_report() insert.
    """
    rows = []
    for inv_id in investigation_ids:
        if random.random() < 0.7:
            report_id = f"report-{inv_id}-seed"
            rows.append((
                report_id,
                inv_id,
                1,
                f"Executive summary for investigation {inv_id}: anomaly investigated and resolved.",
                json.dumps({"confidence": round(random.uniform(0.5, 0.95), 2)}),
            ))
    return rows


def gen_customer_queries(investigation_ids, product_ids, n=80):
    rows = []
    for i in range(n):
        query_id = f"cq-{str(i+1).zfill(4)}"
        created = random_past_date()
        status = random.choice(QUERY_STATUSES)
        resolved_at = (created + timedelta(days=random.randint(1, 10))).isoformat() if status in ("resolved", "closed") else None
        rows.append((
            query_id,
            f"cust-{random.randint(1000,9999)}",
            random.choice(investigation_ids) if random.random() < 0.4 else None,
            random.choice(product_ids) if random.random() < 0.7 else None,
            random.choice(QUERY_TYPES),
            "Customer inquiry regarding recent order",
            "Auto-generated placeholder query description for seeding purposes.",
            random.choice(PRIORITIES),
            status,
            created.isoformat(),
            resolved_at,
        ))
    return rows


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)

    store_rows = gen_stores()
    store_ids = [r[0] for r in store_rows]
    conn.executemany(
        "INSERT OR IGNORE INTO stores (id, store_name, region, country, manager_name) VALUES (?,?,?,?,?)",
        store_rows,
    )

    product_rows = gen_products()
    product_ids = [r[0] for r in product_rows]
    conn.executemany(
        "INSERT OR IGNORE INTO products (product_id, product_name, category, brand, unit_price, status) VALUES (?,?,?,?,?,?)",
        product_rows,
    )

    sku_rows = gen_sku(product_ids)
    conn.executemany(
        "INSERT OR IGNORE INTO sku (sku_id, product_id, sku_code, size, colour, stock_quantity, reorder_lvl) VALUES (?,?,?,?,?,?,?)",
        sku_rows,
    )

    conn.executemany(
        "INSERT OR IGNORE INTO agents (id, agent_name, agent_type, description, capabilities) VALUES (?,?,?,?,?)",
        AGENT_DEFS,
    )
    agent_ids = [a[0] for a in AGENT_DEFS]

    conn.executemany(
        "INSERT OR IGNORE INTO kpis (id, name, category, unit, owner_role) VALUES (?,?,?,?,?)",
        KPI_DEFS,
    )
    kpi_ids = [k[0] for k in KPI_DEFS]

    conn.executemany(
        "INSERT OR IGNORE INTO tool_connectors (id, tool_category, display_name, endpoint_url) VALUES (?,?,?,?)",
        TOOL_CONNECTOR_DEFS,
    )

    investigation_ids = SYNTHETIC_INVESTIGATION_IDS

    conn.executemany(
        """INSERT OR IGNORE INTO agent_executions
           (id, investigation_id, agent_id, status, started_at, completed_at, output)
           VALUES (?,?,?,?,?,?,?)""",
        gen_agent_executions(investigation_ids, agent_ids),
    )

    conn.executemany(
        """INSERT OR IGNORE INTO anomalies
           (id, investigation_id, kpi_id, expected_value, actual_value, deviation_percent, severity)
           VALUES (?,?,?,?,?,?,?)""",
        gen_anomalies(investigation_ids, kpi_ids),
    )

    hypothesis_rows, hypothesis_pairs = gen_hypotheses(investigation_ids)
    conn.executemany(
        """INSERT OR IGNORE INTO hypotheses
           (id, investigation_id, hypothesis_text, confidence_score, confidence_band, uncertainty_note, rank_no)
           VALUES (?,?,?,?,?,?,?)""",
        hypothesis_rows,
    )

    conn.executemany(
        """INSERT OR IGNORE INTO root_causes
           (id, investigation_id, hypothesis_id, cause_category, cause_description, confidence)
           VALUES (?,?,?,?,?,?)""",
        gen_root_causes(hypothesis_pairs),
    )

    conn.executemany(
        """INSERT OR IGNORE INTO reports
           (id, investigation_id, version, executive_summary, report_json)
           VALUES (?,?,?,?,?)""",
        gen_reports(investigation_ids),
    )

    conn.executemany(
        """INSERT OR IGNORE INTO customer_queries
           (query_id, customer_id, investigation_id, product_id, query_type, subject, description,
            priority, status, created_at, resolved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        gen_customer_queries(investigation_ids, product_ids),
    )

    conn.commit()

    tables = ["stores", "products", "sku", "agents", "kpis", "tool_connectors",
              "agent_executions", "anomalies", "hypotheses", "root_causes",
              "reports", "customer_queries"]
    print(f"orchestrator.db seeded at {DB_PATH}")
    for t in tables:
        c = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {c} rows")

    conn.close()


if __name__ == "__main__":
    main()