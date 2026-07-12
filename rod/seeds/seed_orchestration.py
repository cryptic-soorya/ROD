"""
seed_orchestration.py
Seeds the MERGED investigations/orchestration.db -- the single db file that
now holds everything: the real investigation lifecycle tables (owned by
investigations/service.py) PLUS the reference/master data and
investigation-scoped tables that used to live in the separate
mcp_server/db/orchestrator.db.

Run: python seeds/seed_orchestration.py

WHAT CHANGED vs the old seed_orchestrator.py:
    - Target file is now investigations/orchestration.db (matches
      investigations/service.py's DB_PATH and reports/service.py's DB_PATH
      exactly -- confirmed via reports/service.py's own DB_PATH constant).
    - orchestrator.db's `reports` table is GONE. Confirmed dead: production
      reports/service.py writes to *this* file's `reports` table, not the
      one that lived in orchestrator.db. Do not recreate it here.
    - investigation_id columns are now real INTEGER FKs (investigations.id
      is INTEGER AUTOINCREMENT, and everything lives in one file now, so
      SQLite actually enforces this with PRAGMA foreign_keys=ON, same as
      investigations/service.py's get_db()).
    - Because of that enforcement: this script does NOT invent fake
      investigation_id values pointing at investigation rows that don't
      exist. hypotheses / root_causes / agent_executions / anomalies /
      customer_queries are seeded with investigation_id = NULL (all
      nullable in the real schema). Real investigation_id values only ever
      come from the live app via investigations/service.py.
      DO NOT seed fake rows into `investigations` itself here to work around
      this -- that table is owned and written by the live app; a second
      source of rows there is exactly the "disconnected copy" problem this
      whole migration was trying to avoid.
    - NEW: `suppliers` reference table, closing the previously-flagged gap
      (supplier_id existed everywhere with nothing backing it).
    - NEW: `catalog_changes` (renamed + relocated from returns.db's
      product_listing_changes), now keyed by sku_id.
    - product_id -> sku_id on customer_queries.

Depends on seeds/common.py for STORES / PRODUCTS / SKUS / SKU_DETAILS /
SUPPLIERS / SUPPLIER_DETAILS, so ids stay consistent with the retail dbs.
"""
import sqlite3
import os
import random
import json
from datetime import date, timedelta, datetime
from common import (
    PRODUCTS, STORES, SKUS, SKU_DETAILS, SUPPLIERS, SUPPLIER_DETAILS,
    random_date,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "investigations", "orchestration.db")
DB_PATH = os.path.abspath(DB_PATH)

random.seed(7)

# ── Schema ────────────────────────────────────────────────────────────────────
# The investigations / tool_calls / audit_logs / reports block below is
# copied verbatim from investigations/service.py's init_db() so the two
# scripts can never drift apart on those four tables. If that file's schema
# ever changes, update it here too.

SCHEMA_LIVE_TABLES = """
CREATE TABLE IF NOT EXISTS investigations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT    NOT NULL,
    context         TEXT,
    priority        INTEGER NOT NULL DEFAULT 1,
    store_id        TEXT,
    sku             TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',
    iteration_count INTEGER NOT NULL DEFAULT 0,
    report          TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id INTEGER NOT NULL REFERENCES investigations(id),
    tool_name        TEXT    NOT NULL,
    input_args       TEXT    NOT NULL,
    output           TEXT,
    error            TEXT,
    called_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id INTEGER REFERENCES investigations(id),
    event            TEXT    NOT NULL,
    detail           TEXT,
    logged_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id                 TEXT    PRIMARY KEY,
    investigation_id   INTEGER NOT NULL REFERENCES investigations(id),
    version            INTEGER NOT NULL,
    executive_summary  TEXT,
    report_json        TEXT    NOT NULL,
    generated_at       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inv_status   ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_store    ON investigations(store_id);
CREATE INDEX IF NOT EXISTS idx_inv_sku      ON investigations(sku);
CREATE INDEX IF NOT EXISTS idx_inv_created  ON investigations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tc_inv       ON tool_calls(investigation_id);
CREATE INDEX IF NOT EXISTS idx_reports_inv  ON reports(investigation_id);
"""

SCHEMA_REFERENCE_AND_SCOPED = """
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
    sku_id         TEXT PRIMARY KEY,
    product_id     TEXT NOT NULL REFERENCES products(product_id),
    sku_code       TEXT UNIQUE NOT NULL,
    size           TEXT,
    colour         TEXT,
    stock_quantity INTEGER DEFAULT 0,
    reorder_lvl    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suppliers (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    region  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id           TEXT PRIMARY KEY,
    agent_name   TEXT NOT NULL,
    agent_type   TEXT NOT NULL,
    description  TEXT,
    capabilities TEXT,
    is_active    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS kpis (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    unit       TEXT NOT NULL,
    owner_role TEXT
);

CREATE TABLE IF NOT EXISTS tool_connectors (
    id             TEXT PRIMARY KEY,
    tool_category  TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    endpoint_url   TEXT NOT NULL,
    input_schema   TEXT,
    is_active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_executions (
    id                TEXT PRIMARY KEY,
    investigation_id  INTEGER REFERENCES investigations(id),
    agent_id          TEXT REFERENCES agents(id),
    status            TEXT NOT NULL,
    started_at        DATETIME NOT NULL,
    completed_at      DATETIME,
    output            TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    id                 TEXT PRIMARY KEY,
    investigation_id   INTEGER REFERENCES investigations(id),
    kpi_id             TEXT REFERENCES kpis(id),
    expected_value     REAL NOT NULL,
    actual_value       REAL NOT NULL,
    deviation_percent  REAL NOT NULL,
    severity           TEXT NOT NULL,
    detected_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hypotheses (
    id                 TEXT PRIMARY KEY,
    investigation_id   INTEGER REFERENCES investigations(id),
    hypothesis_text    TEXT NOT NULL,
    confidence_score   REAL NOT NULL,
    confidence_band    TEXT NOT NULL,
    uncertainty_note   TEXT,
    rank_no            INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS root_causes (
    id                 TEXT PRIMARY KEY,
    investigation_id   INTEGER REFERENCES investigations(id),
    hypothesis_id      TEXT REFERENCES hypotheses(id),
    cause_category     TEXT NOT NULL,
    cause_description  TEXT NOT NULL,
    confidence         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_queries (
    query_id          TEXT PRIMARY KEY,
    customer_id       TEXT NOT NULL,
    investigation_id  INTEGER REFERENCES investigations(id),
    sku_id            TEXT REFERENCES sku(sku_id),
    query_type        TEXT NOT NULL,
    subject           TEXT NOT NULL,
    description       TEXT NOT NULL,
    priority          TEXT NOT NULL,
    status            TEXT NOT NULL,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at       DATETIME
);

CREATE TABLE IF NOT EXISTS catalog_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          TEXT NOT NULL REFERENCES sku(sku_id),
    change_date     TEXT NOT NULL,
    field_changed   TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      TEXT
);

CREATE INDEX IF NOT EXISTS idx_sku_product          ON sku(product_id);
CREATE INDEX IF NOT EXISTS idx_agent_exec_inv       ON agent_executions(investigation_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_inv        ON anomalies(investigation_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_inv       ON hypotheses(investigation_id);
CREATE INDEX IF NOT EXISTS idx_root_causes_inv      ON root_causes(investigation_id);
CREATE INDEX IF NOT EXISTS idx_customer_queries_inv ON customer_queries(investigation_id);
CREATE INDEX IF NOT EXISTS idx_catalog_changes_sku  ON catalog_changes(sku_id, change_date);
"""

# ── Reference data ─────────────────────────────────────────────────────────

REGIONS   = ["Northeast", "Southeast", "Midwest", "West", "South"]
COUNTRIES = ["USA"]
MANAGERS  = ["A. Patel", "J. Kim", "M. Rossi", "S. Chen", "D. Okafor", None]

BRANDS     = ["Nova", "Everline", "Kestrel", "Bramwell", "Ardent", "Solace"]
CATEGORIES = ["apparel", "footwear", "accessories", "home", "electronics"]

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
    ("tc-006", "customers", "Customer Complaints Tool", "http://localhost:9006/mcp/customers"),
    ("tc-007", "knowledge", "Knowledge Search Tool", "http://localhost:9007/mcp/knowledge"),
]

HYPOTHESIS_TEMPLATES = [
    "Sales drop correlates with a recent listing/price change.",
    "Return spike driven by a sizing or fit issue for this SKU.",
    "Supplier delivery degradation caused a stockout.",
    "Promotion ended and demand reverted (post-promo crash).",
    "Complaint surge traces to a shipping/carrier disruption.",
    "Defect rate increase from a specific supplier batch.",
]

CAUSE_CATEGORIES = ["supplier_quality", "pricing", "listing_change", "logistics", "demand_shift", "inventory"]

QUERY_TYPES     = ["order_status", "product_question", "complaint", "return_request", "general"]
QUERY_STATUSES  = ["open", "in_review", "resolved", "closed"]
PRIORITIES      = ["low", "medium", "high"]


def random_past_date():
    start = date(2025, 1, 1)
    end = date.today()
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


# ── Generators ────────────────────────────────────────────────────────────────

def gen_stores():
    return [
        (s, f"Store {s}", random.choice(REGIONS), random.choice(COUNTRIES), random.choice(MANAGERS))
        for s in STORES
    ]


def gen_products():
    return [
        (p, f"Product {p}", random.choice(CATEGORIES), random.choice(BRANDS),
         round(random.uniform(5, 200), 2), random.choice(["active", "active", "active", "discontinued"]))
        for p in PRODUCTS
    ]


def gen_sku():
    """Uses common.py's already-generated SKU_DETAILS so every other db's
    sku_id values line up with what's actually inserted here."""
    rows = []
    for sku_id, details in SKU_DETAILS.items():
        rows.append((
            sku_id,
            details["product_id"],
            details["sku_code"],
            details["size"],
            details["colour"],
            random.randint(0, 300),   # stock_quantity
            random.randint(10, 50),   # reorder_lvl
        ))
    return rows


def gen_suppliers():
    return [
        (supplier_id, details["name"], details["region"])
        for supplier_id, details in SUPPLIER_DETAILS.items()
    ]


def gen_agent_executions(n=150):
    rows = []
    agent_ids = [a[0] for a in AGENT_DEFS]
    for i in range(n):
        started = random_past_date()
        duration_minutes = random.randint(1, 45)
        completed = started + timedelta(minutes=duration_minutes) if random.random() > 0.05 else None
        rows.append((
            f"exec-{str(i+1).zfill(5)}",
            None,  # investigation_id -- left NULL, see module docstring
            random.choice(agent_ids),
            "completed" if completed else "failed",
            datetime.combine(started, datetime.min.time()).isoformat(),
            datetime.combine(completed, datetime.min.time()).isoformat() if completed else None,
            json.dumps({"note": "seed data, not tied to a real investigation"}),
        ))
    return rows


def gen_anomalies(kpi_ids, n=120):
    rows = []
    for i in range(n):
        expected = round(random.uniform(100, 1000), 2)
        actual = round(expected * random.uniform(0.3, 1.8), 2)
        deviation = round(((actual - expected) / expected) * 100, 2)
        severity = "high" if abs(deviation) > 40 else ("medium" if abs(deviation) > 15 else "low")
        rows.append((
            f"anom-{str(i+1).zfill(5)}",
            None,  # investigation_id -- left NULL, see module docstring
            random.choice(kpi_ids),
            expected, actual, deviation, severity,
        ))
    return rows


def gen_hypotheses(n=100):
    rows = []
    ids = []
    for i in range(n):
        hyp_id = f"hyp-{str(i+1).zfill(5)}"
        confidence = round(random.uniform(0.3, 0.95), 2)
        band = "high" if confidence > 0.75 else ("medium" if confidence > 0.5 else "low")
        rank = random.randint(1, 3)
        ids.append(hyp_id)
        rows.append((
            hyp_id,
            None,  # investigation_id -- left NULL, see module docstring
            random.choice(HYPOTHESIS_TEMPLATES),
            confidence, band,
            None if confidence > 0.6 else "Limited sample size in supporting data",
            rank,
        ))
    return rows, ids


def gen_root_causes(hypothesis_ids):
    rows = []
    for hyp_id in hypothesis_ids:
        if random.random() < 0.6:
            rows.append((
                f"rc-{hyp_id}",
                None,  # investigation_id -- left NULL, see module docstring
                hyp_id,
                random.choice(CAUSE_CATEGORIES),
                "Root cause pattern identified via seeded reference evidence.",
                round(random.uniform(0.6, 0.98), 2),
            ))
    return rows


def gen_customer_queries(n=80):
    rows = []
    for i in range(n):
        created = random_past_date()
        status = random.choice(QUERY_STATUSES)
        resolved_at = (
            (created + timedelta(days=random.randint(1, 10))).isoformat()
            if status in ("resolved", "closed") else None
        )
        rows.append((
            f"cq-{str(i+1).zfill(4)}",
            f"cust-{random.randint(1000, 9999)}",
            None,  # investigation_id -- left NULL, see module docstring
            random.choice(SKUS) if random.random() < 0.7 else None,
            random.choice(QUERY_TYPES),
            "Customer inquiry regarding recent order",
            "Auto-generated placeholder query description for seeding purposes.",
            random.choice(PRIORITIES),
            status,
            created.isoformat(),
            resolved_at,
        ))
    return rows


def gen_catalog_changes(n=2500):
    fields = ["title", "description", "images", "price", "category"]
    editors = ["merchandising_bot", "alice.k", "raj.p", "content_team", "auto_sync"]
    rows = []
    for _ in range(n):
        sku_id = random.choice(SKUS)
        field = random.choice(fields)
        if field == "price":
            old_v, new_v = str(round(random.uniform(5, 200), 2)), str(round(random.uniform(5, 200), 2))
        else:
            old_v, new_v = f"old_{field}_v{random.randint(1,9)}", f"new_{field}_v{random.randint(1,9)}"
        rows.append((sku_id, random_date(), field, old_v, new_v, random.choice(editors)))
    return rows


def main():
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_LIVE_TABLES)
    conn.executescript(SCHEMA_REFERENCE_AND_SCOPED)

    conn.executemany(
        "INSERT OR IGNORE INTO stores (id, store_name, region, country, manager_name) VALUES (?,?,?,?,?)",
        gen_stores(),
    )

    conn.executemany(
        "INSERT OR IGNORE INTO products (product_id, product_name, category, brand, unit_price, status) VALUES (?,?,?,?,?,?)",
        gen_products(),
    )

    conn.executemany(
        "INSERT OR IGNORE INTO sku (sku_id, product_id, sku_code, size, colour, stock_quantity, reorder_lvl) VALUES (?,?,?,?,?,?,?)",
        gen_sku(),
    )

    # Self-check: if any sku row got silently dropped (e.g. a sku_code
    # collision hitting the UNIQUE constraint via INSERT OR IGNORE), every
    # downstream table that samples from common.SKUS would reference a
    # sku_id that doesn't actually exist in this table -- and since those
    # inserts are same-file FKs now, they'd fail (or worse, also silently
    # drop rows if they use OR IGNORE). Fail loudly here instead, at the
    # source, rather than several inserts later.
    actual_sku_count = conn.execute("SELECT COUNT(*) FROM sku").fetchone()[0]
    expected_sku_count = len(SKU_DETAILS)
    if actual_sku_count != expected_sku_count:
        raise RuntimeError(
            f"sku table has {actual_sku_count} rows but common.SKU_DETAILS has "
            f"{expected_sku_count} entries -- some sku_code collided (UNIQUE "
            f"constraint) and was dropped by INSERT OR IGNORE. Fix the collision "
            f"in common.py's _gen_skus() before re-running; do not proceed with "
            f"mismatched sku_id references downstream."
        )

    conn.executemany(
        "INSERT OR IGNORE INTO suppliers (id, name, region) VALUES (?,?,?)",
        gen_suppliers(),
    )

    conn.executemany(
        "INSERT OR IGNORE INTO agents (id, agent_name, agent_type, description, capabilities) VALUES (?,?,?,?,?)",
        AGENT_DEFS,
    )

    conn.executemany(
        "INSERT OR IGNORE INTO kpis (id, name, category, unit, owner_role) VALUES (?,?,?,?,?)",
        KPI_DEFS,
    )
    kpi_ids = [k[0] for k in KPI_DEFS]

    conn.executemany(
        "INSERT OR IGNORE INTO tool_connectors (id, tool_category, display_name, endpoint_url) VALUES (?,?,?,?)",
        TOOL_CONNECTOR_DEFS,
    )

    conn.executemany(
        """INSERT OR IGNORE INTO agent_executions
           (id, investigation_id, agent_id, status, started_at, completed_at, output)
           VALUES (?,?,?,?,?,?,?)""",
        gen_agent_executions(),
    )

    conn.executemany(
        """INSERT OR IGNORE INTO anomalies
           (id, investigation_id, kpi_id, expected_value, actual_value, deviation_percent, severity)
           VALUES (?,?,?,?,?,?,?)""",
        gen_anomalies(kpi_ids),
    )

    hypothesis_rows, hypothesis_ids = gen_hypotheses()
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
        gen_root_causes(hypothesis_ids),
    )

    conn.executemany(
        """INSERT OR IGNORE INTO customer_queries
           (query_id, customer_id, investigation_id, sku_id, query_type, subject, description,
            priority, status, created_at, resolved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        gen_customer_queries(),
    )

    conn.executemany(
        "INSERT INTO catalog_changes (sku_id, change_date, field_changed, old_value, new_value, changed_by) VALUES (?,?,?,?,?,?)",
        gen_catalog_changes(),
    )

    conn.commit()

    tables = ["stores", "products", "sku", "suppliers", "agents", "kpis", "tool_connectors",
              "agent_executions", "anomalies", "hypotheses", "root_causes",
              "customer_queries", "catalog_changes"]
    print(f"investigations/orchestration.db (merged) seeded at {DB_PATH}")
    for t in tables:
        c = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {c} rows")
    print("  investigations / tool_calls / audit_logs / reports: NOT seeded here")
    print("  (owned + written by the live app via investigations/service.py + reports/service.py)")

    conn.close()


if __name__ == "__main__":
    main()
