"""
investigations/models.py
OWNER: Teammate B

Pydantic models for Investigation, ToolCall, and Report.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────────

class InvestigationStatus(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    ESCALATED   = "escalated"


class AnomalyCategory(str, Enum):
    SALES_DROP             = "sales_drop"
    INVENTORY_SPIKE        = "inventory_spike"
    RETURN_SURGE           = "return_surge"
    SUPPLIER_DELAY         = "supplier_delay"
    CUSTOMER_COMPLAINT     = "customer_complaint"
    PROMOTION_UNDERPERFORM = "promotion_underperform"
    UNKNOWN                = "unknown"


# ── ToolCall ───────────────────────────────────────────────────────────────────

class ToolCall(BaseModel):
    id:               int
    investigation_id: int
    tool_name:        str
    input_args:       dict
    output:           Optional[Any] = None
    error:            Optional[str] = None
    called_at:        datetime

    class Config:
        from_attributes = True


# ── Report ─────────────────────────────────────────────────────────────────────

class Report(BaseModel):
    """Structured report attached to a completed or escalated investigation."""
    anomaly_category: Optional[AnomalyCategory] = None
    confidence_score: Optional[float]            = None   # 0.0 – 1.0
    root_cause:       Optional[str]              = None
    recommendations:  List[str]                  = []
    evidence_trail:   List[str]                  = []     # human-readable steps
    generated_at:     Optional[datetime]         = None


# ── Investigation ──────────────────────────────────────────────────────────────

class InvestigationCreate(BaseModel):
    """Body for POST /api/v1/detective/investigate."""
    query:    str  = Field(..., min_length=5, max_length=1000,
                           example="Why did sales of SKU-42 drop 35% last week?")
    context:  Optional[dict] = Field(
                           None, example={"store_id": "NYC-01", "sku": "SKU-42"})
    priority: int  = Field(1, ge=1, le=5,
                           description="1 = lowest priority, 5 = highest")


class InvestigationResponse(BaseModel):
    """Full investigation record — returned by GET /investigation/{id}."""
    id:               int
    query:            str
    context:          Optional[dict]
    priority:         int
    status:           InvestigationStatus
    iteration_count:  int                  # how many ReAct steps have run so far
    created_at:       datetime
    updated_at:       datetime
    completed_at:     Optional[datetime]
    report:           Optional[Report]
    tool_calls:       List[ToolCall] = []

    class Config:
        from_attributes = True


class InvestigationListItem(BaseModel):
    """Compact row used in the paginated list response."""
    id:               int
    query:            str
    status:           InvestigationStatus
    priority:         int
    store_id:         Optional[str]        # extracted from context for filtering
    sku:              Optional[str]        # extracted from context for filtering
    created_at:       datetime
    completed_at:     Optional[datetime]
    confidence_score: Optional[float]

    class Config:
        from_attributes = True


class PaginatedInvestigations(BaseModel):
    total:    int
    page:     int
    per_page: int
    pages:    int
    items:    List[InvestigationListItem]
