# tools/tool_8_delivery.py
# MCP Tool: get_delivery_performance
# Scope required: read:suppliers
# Queries suppliers.db for delivery metrics vs baseline
# Sets degradation_flag = True when current > 1.5x baseline

import sqlite3
import os

DB_PATH = os.getenv("SUPPLIERS_DB_PATH", "./suppliers.db")

def get_delivery_performance(supplier_id: str, period: str = "last_30_days") -> dict:
    """
    Returns delivery performance for a supplier vs their baseline.
    
    supplier_id: e.g. "SUP-019" — must exist in suppliers.db
    period: "last_7_days" | "last_30_days" | "last_quarter" (default: last_30_days)
    """
    
    # Validate period — only these 3 values are allowed
    valid_periods = {"last_7_days", "last_30_days", "last_quarter"}
    if period not in valid_periods:
        return {
            "error": "INVALID_PERIOD",
            "message": f"period must be one of: {', '.join(valid_periods)}",
            "tool": "get_delivery_performance"
        }
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT avg_delivery_days_current, avg_delivery_days_baseline, defect_rate
            FROM supplier_deliveries
            WHERE supplier_id = ? AND period = ?
        """, (supplier_id, period))
        
        row = cursor.fetchone()
        conn.close()
        
        # If no row found, supplier doesn't exist — return structured error
        # The agent will reason around this, not crash
        if not row:
            return {
                "error": "SUPPLIER_NOT_FOUND",
                "message": f"supplier_id {supplier_id} not found for period {period}",
                "tool": "get_delivery_performance"
            }
        
        current, baseline, defect_rate = row
        
        # Key business rule from spec:
        # degradation_flag = True when current > 1.5 × baseline
        # Example: baseline=7.0, current=11.4 → 11.4 > 10.5 → True
        degradation_flag = current > (1.5 * baseline)
        
        return {
            "supplier_id": supplier_id,
            "period": period,
            "avg_delivery_days_current": current,
            "avg_delivery_days_baseline": baseline,
            "defect_rate": defect_rate,
            "degradation_flag": degradation_flag
        }
        
    except sqlite3.Error as e:
        # DB errors are caught and returned as structured objects
        # The investigation continues — the agent tries something else
        return {
            "error": "DB_ERROR",
            "message": str(e),
            "tool": "get_delivery_performance"
        }