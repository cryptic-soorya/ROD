"""
test_mcp_tools_pytest.py

Pytest suite for the retail MCP tool set:
    sales.py, inventory.py, returns.py, promotions.py, customers.py, suppliers.py

Design notes
------------
Every tool follows the same shape:

    @mcp.tool()
    def some_tool(...):
        err = check_scope(get_token_payload(), "read:xxx", tool_name="some_tool")
        if err:
            return err
        conn = _connect()          # psycopg2.connect(...)
        try:
            rows = _rows(conn, sql, params)   # cur.execute + fetchall
            ...
        finally:
            conn.close()

So instead of hitting a real Postgres instance, these tests:
  1. Monkeypatch `check_scope` / `get_token_payload` in each tool module so
     every test controls authorization explicitly (either "authorized" or
     a specific scope-denial error), rather than depending on a real JWT.
  2. Monkeypatch `psycopg2.connect` (as imported inside each tool module)
     with a FakeConnection that replays a queue of canned result sets, one
     per `cur.execute(...)` call, in the order the tool issues them.

This keeps the tests fast, deterministic, and independent of any database,
while still exercising the *real* business logic in each tool (flag
calculations, error shapes, percentage math, date validation, etc).

Run with:  pytest -v test_mcp_tools_pytest.py
"""

import os
import sys

# Tool modules read these at import time (module-level `os.getenv(...)` calls
# for DSNs). Values don't need to be real since psycopg2.connect is mocked,
# but they must be set before the modules are imported.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SALES_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("INVENTORY_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("RETURNS_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("PROMOTIONS_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("CUSTOMERS_DB_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("SUPPLIERS_DB_URL", os.environ["DATABASE_URL"])

import psycopg2
import pytest

from mcp_server.tools import sales
from mcp_server.tools import inventory
from mcp_server.tools import returns
from mcp_server.tools import promotions
from mcp_server.tools import customers
from mcp_server.tools import suppliers


# ---------------------------------------------------------------------------
# Fake DB plumbing
# ---------------------------------------------------------------------------

class FakeCursor:
    """Stands in for a psycopg2 RealDictCursor.

    `results_queue` is a list shared with the FakeConnection; each call to
    `execute()` consumes the next entry and `fetchall()` returns it.
    """

    def __init__(self, results_queue, calls_log):
        self._results_queue = results_queue
        self._calls_log = calls_log
        self._last_result = None

    def execute(self, sql, params=()):
        self._calls_log.append((sql.strip(), params))
        if not self._results_queue:
            raise AssertionError(
                "FakeCursor.execute() called more times than results were queued. "
                f"SQL was: {sql[:80]!r}"
            )
        self._last_result = self._results_queue.pop(0)

    def fetchall(self):
        return self._last_result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    """Stands in for a psycopg2 connection.

    `results_by_call` is a list of row-lists (each a list of dicts), consumed
    in order as the tool under test issues successive queries.
    """

    def __init__(self, results_by_call=None, raise_on_execute=None):
        self.results_queue = list(results_by_call or [])
        self.calls = []
        self.closed = False
        self._raise_on_execute = raise_on_execute

    def cursor(self):
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        return FakeCursor(self.results_queue, self.calls)

    def close(self):
        self.closed = True


def make_conn(monkeypatch, module, results_by_call=None, raise_error=None):
    """Patch `psycopg2.connect` as seen by `module` to return a FakeConnection.

    If `raise_error` is given, the *cursor* raises it (simulating a
    psycopg2.Error surfacing mid-query), which is what each tool's
    `except psycopg2.Error` branch is written to catch.
    """
    conn = FakeConnection(results_by_call=results_by_call, raise_on_execute=raise_error)
    monkeypatch.setattr(module.psycopg2, "connect", lambda *a, **k: conn)
    return conn


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

TOOL_MODULES = [sales, inventory, returns, promotions, customers, suppliers]


@pytest.fixture(autouse=True)
def authorized_by_default(monkeypatch):
    """By default every tool call is treated as authorized.

    Individual tests that want to exercise scope denial override
    `check_scope` on the specific module under test.
    """
    for mod in TOOL_MODULES:
        monkeypatch.setattr(mod, "get_token_payload", lambda: {"sub": "test-agent"})
        monkeypatch.setattr(mod, "check_scope", lambda payload, scope, tool_name=None: None)


def deny_scope(monkeypatch, module, missing_scope, tool_name=None):
    """Make `module`'s check_scope reject the call, as if the token lacked
    `missing_scope`."""
    err = {"error": "MISSING_SCOPE", "message": f"missing {missing_scope}", "tool": tool_name}
    monkeypatch.setattr(module, "check_scope", lambda payload, scope, tool_name=None: err)
    return err


# ---------------------------------------------------------------------------
# sales.py
# ---------------------------------------------------------------------------

class TestGetSalesData:
    def test_normal_growth(self, monkeypatch):
        make_conn(
            monkeypatch,
            sales,
            results_by_call=[
                [{"revenue": 1500.0}],   # current period
                [{"revenue": 1000.0}],   # previous period
                [{"1": 1}],              # store exists check
            ],
        )
        result = sales.get_sales_data("STORE-1", "last_30_days")
        assert result["store_id"] == "STORE-1"
        assert result["revenue_current_period"] == 1500.0
        assert result["revenue_previous_period"] == 1000.0
        assert result["change_pct"] == 50.0

    def test_previous_zero_gives_none_change_pct(self, monkeypatch):
        make_conn(
            monkeypatch,
            sales,
            results_by_call=[
                [{"revenue": 500.0}],
                [{"revenue": 0}],
                [{"1": 1}],
            ],
        )
        result = sales.get_sales_data("STORE-1")
        assert result["change_pct"] is None

    def test_store_not_found(self, monkeypatch):
        make_conn(
            monkeypatch,
            sales,
            results_by_call=[
                [{"revenue": 0}],
                [{"revenue": 0}],
                [],  # exists check comes back empty -> store never sold anything
            ],
        )
        result = sales.get_sales_data("GHOST-STORE")
        assert result["error"] == "STORE_NOT_FOUND"
        assert result["tool"] == "get_sales_data"

    def test_invalid_period(self, monkeypatch):
        make_conn(monkeypatch, sales, results_by_call=[])
        result = sales.get_sales_data("STORE-1", period="last_century")
        assert result["error"] == "INVALID_PERIOD"

    def test_db_error_is_caught(self, monkeypatch):
        make_conn(monkeypatch, sales, raise_error=psycopg2.Error("connection reset"))
        result = sales.get_sales_data("STORE-1")
        assert result["error"] == "DB_ERROR"
        assert result["tool"] == "get_sales_data"

    def test_missing_scope_short_circuits_before_any_query(self, monkeypatch):
        deny_scope(monkeypatch, sales, "read:sales", tool_name="get_sales_data")
        conn = make_conn(monkeypatch, sales, results_by_call=[])
        result = sales.get_sales_data("STORE-1")
        assert result["error"] == "MISSING_SCOPE"
        assert conn.calls == []  # never touched the DB


class TestGetStoresWithSalesDecline:
    def test_returns_only_declining_stores_worst_first(self, monkeypatch):
        make_conn(
            monkeypatch,
            sales,
            results_by_call=[
                [
                    {"store_id": "S1", "current": 800.0, "previous": 1000.0},   # -20%
                    {"store_id": "S2", "current": 1200.0, "previous": 1000.0},  # +20%, excluded
                    {"store_id": "S3", "current": 100.0, "previous": 1000.0},   # -90%
                ],
            ],
        )
        result = sales.get_stores_with_sales_decline()
        store_ids = [s["store_id"] for s in result["stores"]]
        assert store_ids == ["S3", "S1"]  # worst decline first

    def test_limit_is_clamped_to_range(self, monkeypatch):
        make_conn(monkeypatch, sales, results_by_call=[[]])
        result = sales.get_stores_with_sales_decline(limit=100)
        # limit itself isn't in the output, but this at least confirms the
        # call succeeds with an out-of-range limit rather than erroring.
        assert result["stores"] == []

    def test_invalid_period(self, monkeypatch):
        make_conn(monkeypatch, sales, results_by_call=[])
        result = sales.get_stores_with_sales_decline(period="nonsense")
        assert result["error"] == "INVALID_PERIOD"


# ---------------------------------------------------------------------------
# inventory.py
# ---------------------------------------------------------------------------

class TestGetInventoryLevels:
    def test_found_above_reorder_point(self, monkeypatch):
        make_conn(
            monkeypatch,
            inventory,
            results_by_call=[[{
                "inv_id": 1, "sku_id": "SKU-1", "store_id": "STORE-1",
                "stock_on_hand": 50, "reorder_point": 10, "last_audited": "2026-07-01",
            }]],
        )
        result = inventory.get_inventory_levels("SKU-1", "STORE-1")
        assert result["units_available"] == 50
        assert result["below_reorder_point"] is False
        assert result["stockout_flag"] is False

    def test_below_reorder_point_and_stockout(self, monkeypatch):
        make_conn(
            monkeypatch,
            inventory,
            results_by_call=[[{
                "inv_id": 2, "sku_id": "SKU-2", "store_id": "STORE-1",
                "stock_on_hand": 0, "reorder_point": 10, "last_audited": "2026-07-01",
            }]],
        )
        result = inventory.get_inventory_levels("SKU-2", "STORE-1")
        assert result["below_reorder_point"] is True
        assert result["stockout_flag"] is True

    def test_no_record_found(self, monkeypatch):
        make_conn(monkeypatch, inventory, results_by_call=[[]])
        result = inventory.get_inventory_levels("SKU-404", "STORE-1")
        assert "error" in result
        assert result["sku"] == "SKU-404"

    def test_db_error(self, monkeypatch):
        make_conn(monkeypatch, inventory, raise_error=psycopg2.Error("timeout"))
        result = inventory.get_inventory_levels("SKU-1", "STORE-1")
        assert result["error"] == "DB_ERROR"

    def test_missing_scope(self, monkeypatch):
        deny_scope(monkeypatch, inventory, "read:inventory", tool_name="get_inventory_levels")
        result = inventory.get_inventory_levels("SKU-1", "STORE-1")
        assert result["error"] == "MISSING_SCOPE"


class TestGetReplenishmentHistory:
    def test_empty_list_is_valid_not_an_error(self, monkeypatch):
        make_conn(monkeypatch, inventory, results_by_call=[[]])
        result = inventory.get_replenishment_history("SKU-1", "STORE-1")
        assert result["replenishments"] == []
        assert "error" not in result

    def test_normal_history(self, monkeypatch):
        make_conn(
            monkeypatch,
            inventory,
            results_by_call=[[{
                "order_date": "2026-06-01", "received_date": "2026-06-05",
                "units_ordered": 100, "units_received": 90, "supplier_id": "SUP-1",
            }]],
        )
        result = inventory.get_replenishment_history("SKU-1", "STORE-1", days=60)
        assert result["period_days"] == 60
        assert result["replenishments"][0]["supplier_id"] == "SUP-1"

    def test_non_positive_days_is_rejected(self, monkeypatch):
        make_conn(monkeypatch, inventory, results_by_call=[])
        result = inventory.get_replenishment_history("SKU-1", "STORE-1", days=0)
        assert "error" in result


# ---------------------------------------------------------------------------
# returns.py
# ---------------------------------------------------------------------------

class TestGetReturnReasons:
    def test_percentages_sum_to_one(self, monkeypatch):
        make_conn(
            monkeypatch,
            returns,
            results_by_call=[[
                {"reason_code": "SIZE", "reason_text": "Wrong size", "count": 7},
                {"reason_code": "DAMAGED", "reason_text": "Damaged", "count": 2},
                {"reason_code": "OTHER", "reason_text": "Other", "count": 1},
            ]],
        )
        result = returns.get_return_reasons("SKU-1", days=14)
        assert result["total_returns"] == 10
        assert abs(sum(result["reasons"].values()) - 1.0) <= 0.01
        assert result["low_sample_warning"] is False  # 10 is not < 10

    def test_low_sample_warning(self, monkeypatch):
        make_conn(
            monkeypatch,
            returns,
            results_by_call=[[{"reason_code": "SIZE", "reason_text": "Wrong size", "count": 3}]],
        )
        result = returns.get_return_reasons("SKU-1")
        assert result["low_sample_warning"] is True

    def test_zero_returns(self, monkeypatch):
        make_conn(monkeypatch, returns, results_by_call=[[]])
        result = returns.get_return_reasons("SKU-1")
        assert result["total_returns"] == 0
        assert result["low_sample_warning"] is True
        assert result["reasons"] == {}

    def test_days_clamped_to_max(self, monkeypatch):
        make_conn(monkeypatch, returns, results_by_call=[[]])
        result = returns.get_return_reasons("SKU-1", days=10_000)
        assert result["period_days"] == 365

    def test_db_error(self, monkeypatch):
        make_conn(monkeypatch, returns, raise_error=psycopg2.Error("boom"))
        result = returns.get_return_reasons("SKU-1")
        assert result["error"] == "DB_ERROR"


class TestGetProductListingChanges:
    def test_invalid_date_format(self, monkeypatch):
        make_conn(monkeypatch, returns, results_by_call=[])
        result = returns.get_product_listing_changes("SKU-1", "07/01/2026")
        assert "error" in result

    def test_future_date_rejected(self, monkeypatch):
        make_conn(monkeypatch, returns, results_by_call=[])
        result = returns.get_product_listing_changes("SKU-1", "2099-01-01")
        assert "error" in result

    def test_no_changes_found(self, monkeypatch):
        make_conn(monkeypatch, returns, results_by_call=[[]])
        result = returns.get_product_listing_changes("SKU-1", "2026-01-01")
        assert result["fields_changed"] == []
        assert result["gap_days"] is None

    def test_normal_changes(self, monkeypatch):
        make_conn(
            monkeypatch,
            returns,
            results_by_call=[[
                {
                    "field_changed": "price", "old_value": "19.99", "new_value": "24.99",
                    "change_date": "2026-06-15", "changed_by": "merch-team",
                },
                {
                    "field_changed": "size_chart", "old_value": "v1", "new_value": "v2",
                    "change_date": "2026-05-01", "changed_by": "merch-team",
                },
            ]],
        )
        result = returns.get_product_listing_changes("SKU-1", "2026-01-01")
        assert result["fields_changed"] == ["price", "size_chart"]
        assert result["change_date"] == "2026-06-15"
        assert result["total_changes_in_period"] == 2

    def test_missing_scope(self, monkeypatch):
        deny_scope(monkeypatch, returns, "read:returns", tool_name="get_product_listing_changes")
        result = returns.get_product_listing_changes("SKU-1", "2026-01-01")
        assert result["error"] == "MISSING_SCOPE"


# ---------------------------------------------------------------------------
# promotions.py
# ---------------------------------------------------------------------------

class TestGetPromotionPerformance:
    def test_not_found(self, monkeypatch):
        make_conn(monkeypatch, promotions, results_by_call=[[]])
        result = promotions.get_promotion_performance("PROMO-404")
        assert "error" in result

    def test_underperformance_flag_true(self, monkeypatch):
        make_conn(
            monkeypatch,
            promotions,
            results_by_call=[[{
                "promo_id": "PROMO-1", "sku_id": "SKU-1",
                "start_date": "2026-06-01", "end_date": "2026-06-15",
                "discount_pct": 10, "units_sold": 105, "baseline_units": 100,
                "revenue": 1000.0, "margin_impact": -50.0,
            }]],
        )
        result = promotions.get_promotion_performance("PROMO-1")
        # actual uplift = 5%, projected = 20% -> 5 < 0.5*20=10 -> underperforming
        assert result["actual_uplift_pct"] == 5.0
        assert result["projected_uplift_pct"] == 20.0
        assert result["underperformance_flag"] is True

    def test_underperformance_flag_false(self, monkeypatch):
        make_conn(
            monkeypatch,
            promotions,
            results_by_call=[[{
                "promo_id": "PROMO-2", "sku_id": "SKU-1",
                "start_date": "2026-06-01", "end_date": "2026-06-15",
                "discount_pct": 10, "units_sold": 130, "baseline_units": 100,
                "revenue": 1500.0, "margin_impact": 20.0,
            }]],
        )
        result = promotions.get_promotion_performance("PROMO-2")
        # actual uplift = 30%, projected = 20% -> not underperforming
        assert result["underperformance_flag"] is False

    def test_zero_baseline_gives_none_actual_uplift(self, monkeypatch):
        make_conn(
            monkeypatch,
            promotions,
            results_by_call=[[{
                "promo_id": "PROMO-3", "sku_id": "SKU-1",
                "start_date": "2026-06-01", "end_date": "2026-06-15",
                "discount_pct": 10, "units_sold": 10, "baseline_units": 0,
                "revenue": 100.0, "margin_impact": 0.0,
            }]],
        )
        result = promotions.get_promotion_performance("PROMO-3")
        assert result["actual_uplift_pct"] is None
        assert result["underperformance_flag"] is False

    def test_db_error(self, monkeypatch):
        make_conn(monkeypatch, promotions, raise_error=psycopg2.Error("nope"))
        result = promotions.get_promotion_performance("PROMO-1")
        assert result["error"] == "DB_ERROR"

    def test_missing_scope(self, monkeypatch):
        deny_scope(monkeypatch, promotions, "read:promotions", tool_name="get_promotion_performance")
        conn = make_conn(monkeypatch, promotions, results_by_call=[])
        result = promotions.get_promotion_performance("PROMO-1")
        assert result["error"] == "MISSING_SCOPE"
        assert conn.calls == []


# ---------------------------------------------------------------------------
# customers.py
# ---------------------------------------------------------------------------

class TestGetCustomerComplaints:
    def test_grouped_view_without_category(self, monkeypatch):
        make_conn(
            monkeypatch,
            customers,
            results_by_call=[[
                {"category": "sizing", "count": 12},
                {"category": "shipping", "count": 5},
            ]],
        )
        result = customers.get_customer_complaints("2026-01-01,2026-06-30")
        assert result["grouped_by_category"] == {"sizing": 12, "shipping": 5}
        assert result["dominant_category"] == "sizing"
        assert result["total_complaints"] == 17

    def test_filtered_view_with_category(self, monkeypatch):
        make_conn(
            monkeypatch,
            customers,
            results_by_call=[[
                {"complaint_id": "C1", "category": "sizing", "date": "2026-05-01",
                 "description": "Runs small"},
            ]],
        )
        result = customers.get_customer_complaints("2026-01-01,2026-06-30", category="sizing")
        assert result["category_filter"] == "sizing"
        assert result["total"] == 1
        assert result["complaints"][0]["complaint_id"] == "C1"

    def test_invalid_date_range_format(self, monkeypatch):
        make_conn(monkeypatch, customers, results_by_call=[])
        result = customers.get_customer_complaints("2026-01-01")
        assert "error" in result

    def test_no_complaints_grouped_view(self, monkeypatch):
        make_conn(monkeypatch, customers, results_by_call=[[]])
        result = customers.get_customer_complaints("2026-01-01,2026-06-30")
        assert result["grouped_by_category"] == {}
        assert result["dominant_category"] is None
        assert result["total_complaints"] == 0

    def test_missing_scope(self, monkeypatch):
        deny_scope(monkeypatch, customers, "read:customers", tool_name="get_customer_complaints")
        result = customers.get_customer_complaints("2026-01-01,2026-06-30")
        assert result["error"] == "MISSING_SCOPE"


# ---------------------------------------------------------------------------
# suppliers.py
# ---------------------------------------------------------------------------

class TestGetDeliveryPerformance:
    def test_degradation_flag_true(self, monkeypatch):
        make_conn(
            monkeypatch,
            suppliers,
            results_by_call=[[{
                "current_days": 9.0, "baseline_days": 5.0, "defect_rate": 0.02,
            }]],
        )
        result = suppliers.get_delivery_performance("SUP-019", "last_30_days")
        # 9 > 1.5 * 5 (=7.5) -> degraded
        assert result["degradation_flag"] is True
        assert result["avg_delivery_days_current"] == 9.0

    def test_degradation_flag_false(self, monkeypatch):
        make_conn(
            monkeypatch,
            suppliers,
            results_by_call=[[{
                "current_days": 5.5, "baseline_days": 5.0, "defect_rate": 0.01,
            }]],
        )
        result = suppliers.get_delivery_performance("SUP-022", "last_30_days")
        assert result["degradation_flag"] is False

    def test_supplier_not_found(self, monkeypatch):
        make_conn(
            monkeypatch,
            suppliers,
            results_by_call=[[{"current_days": None, "baseline_days": None, "defect_rate": None}]],
        )
        result = suppliers.get_delivery_performance("SUP-999")
        assert result["error"] == "SUPPLIER_NOT_FOUND"

    def test_invalid_period(self, monkeypatch):
        make_conn(monkeypatch, suppliers, results_by_call=[])
        result = suppliers.get_delivery_performance("SUP-019", period="last_decade")
        assert result["error"] == "INVALID_PERIOD"

    def test_db_error(self, monkeypatch):
        make_conn(monkeypatch, suppliers, raise_error=psycopg2.Error("connection lost"))
        result = suppliers.get_delivery_performance("SUP-019")
        assert result["error"] == "DB_ERROR"

    def test_unauthenticated_before_startup_check(self, monkeypatch):
        # Mirrors test_mcp_tools.py's manual check: no token validated yet.
        monkeypatch.setattr(suppliers, "get_token_payload", lambda: None)
        monkeypatch.setattr(
            suppliers, "check_scope",
            lambda payload, scope, tool_name=None: (
                {"error": "UNAUTHENTICATED", "message": "no token", "tool": tool_name}
                if payload is None else None
            ),
        )
        conn = make_conn(monkeypatch, suppliers, results_by_call=[])
        result = suppliers.get_delivery_performance("SUP-019")
        assert result["error"] == "UNAUTHENTICATED"
        assert conn.calls == []

    def test_missing_scope(self, monkeypatch):
        deny_scope(monkeypatch, suppliers, "read:suppliers", tool_name="get_delivery_performance")
        result = suppliers.get_delivery_performance("SUP-019")
        assert result["error"] == "MISSING_SCOPE"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))