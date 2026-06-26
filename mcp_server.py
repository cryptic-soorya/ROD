# mcp_server.py
# This is the MCP server that exposes your tools to the ReAct agent.
# The agent calls these tools by name during its reasoning loop.
# Transport: stdio (agent talks to this process via stdin/stdout)
# Run: python mcp_server.py

from fastmcp import FastMCP
from tools.tool_8_delivery import get_delivery_performance
from tools.tool_9_knowledge import knowledge_search
import os
import jwt  # PyJWT

# FastMCP is the framework that handles the MCP protocol for you.
# You just define tools with @mcp.tool() and it handles the rest.
mcp = FastMCP("ROD MCP Server")

# ── Scope validation ──────────────────────────────────────────────────────────
# The spec says scope is checked PER TOOL CALL before any DB connection opens.
# The agent's JWT is injected via environment variable MCP_AUTH_TOKEN at startup.
# The LLM never sees this token — it's purely server-side.

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

def check_scope(required_scope: str) -> None:
    """
    Decodes the agent's JWT and checks if the required scope is present.
    Raises PermissionError if scope is missing or token is invalid.
    Called at the top of every tool — before any DB query runs.
    """
    if not MCP_AUTH_TOKEN:
        raise PermissionError("MCP_AUTH_TOKEN not set — server misconfigured")
    
    try:
        # Decode and verify the JWT signature
        payload = jwt.decode(
            MCP_AUTH_TOKEN,
            JWT_SECRET,
            algorithms=["HS256"]
        )
        scopes = payload.get("scopes", [])
        
        if required_scope not in scopes:
            raise PermissionError(
                f"Token missing required scope: {required_scope}"
            )
    except jwt.ExpiredSignatureError:
        raise PermissionError("Agent token expired — investigation session ended")
    except jwt.InvalidTokenError as e:
        raise PermissionError(f"Invalid agent token: {e}")


# ── Tool 8: get_delivery_performance ─────────────────────────────────────────
# Required scope: read:suppliers
# The @mcp.tool() decorator registers this function as an MCP tool.
# The agent sees the function name, parameters, and docstring.
# It uses the docstring to decide WHEN to call this tool.

@mcp.tool()
def mcp_get_delivery_performance(
    supplier_id: str,
    period: str = "last_30_days"
) -> dict:
    """
    Returns delivery performance metrics for a supplier compared to their baseline.
    Use this when investigating supply chain issues, stockouts, or when a supplier
    may be causing downstream inventory or promotion problems.
    
    supplier_id: supplier identifier e.g. 'SUP-019'
    period: 'last_7_days' | 'last_30_days' | 'last_quarter' (default: last_30_days)
    
    Returns avg_delivery_days_current, avg_delivery_days_baseline, defect_rate,
    and degradation_flag (True when current > 150% of baseline).
    """
    # Scope check FIRST — before touching the database
    try:
        check_scope("read:suppliers")
    except PermissionError as e:
        return {"error": "SCOPE_ERROR", "message": str(e), "tool": "get_delivery_performance"}
    
    # Call your actual business logic function
    return get_delivery_performance(supplier_id, period)


# ── Tool 9: knowledge_search ──────────────────────────────────────────────────
# Required scope: read:knowledge
# The agent calls this MULTIPLE TIMES per investigation with evolving queries
# as it gathers more evidence and refines what it's looking for.

@mcp.tool()
def mcp_knowledge_search(
    query: str,
    n_results: int = 2
) -> dict:
    """
    Semantic search over the retail knowledge base containing SOPs and past
    investigation case summaries. Use this to find relevant standard operating
    procedures or historical cases that match the current anomaly pattern.
    Can be called multiple times per investigation with different queries
    as new evidence emerges.
    
    query: natural language description of what you're looking for
           e.g. 'supplier size chart update impact on return rate'
    n_results: number of results to return, between 1 and 5 (default: 2)
    
    Returns documents ranked by semantic similarity score (0.0 to 1.0).
    """
    try:
        check_scope("read:knowledge")
    except PermissionError as e:
        return {"error": "SCOPE_ERROR", "message": str(e), "tool": "knowledge_search"}
    
    return knowledge_search(query, n_results)


# ── Start the server ──────────────────────────────────────────────────────────
# stdio transport means the agent talks to this process via stdin/stdout pipes.
# This is standard MCP — the agent spawns this process and communicates through it.

if __name__ == "__main__":
    print("ROD MCP Server starting — tools: get_delivery_performance, knowledge_search")
    mcp.run(transport="stdio")