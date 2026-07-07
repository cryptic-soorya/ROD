import os
os.environ.setdefault("SUPPLIERS_DB_PATH", "./mcp_server/db/suppliers.db")
os.environ.setdefault("CHROMA_DB_PATH", "./knowledge_base/chroma_db")
os.environ.setdefault("MCP_JWT_SECRET", "test-secret-do-not-use-in-prod")

import time
import jwt as pyjwt

from mcp_server import auth_middleware
from mcp_server.tools.suppliers import get_delivery_performance
from mcp_server.tools.knowledge import knowledge_search

print("=== Testing scope enforcement (no token validated yet) ===")
print(get_delivery_performance("SUP-019", "last_30_days"))
# Should return an UNAUTHENTICATED error dict — startup_check() hasn't run yet

# Simulate what main.py / mcp_server/server.py do at startup: validate the
# agent token once so get_token_payload() has something for check_scope to read.
token = pyjwt.encode(
    {"sub": "rod-service", "scopes": ["read:suppliers", "read:knowledge"],
     "exp": int(time.time()) + 3600},
    os.environ["MCP_JWT_SECRET"],
    algorithm="HS256",
)
auth_middleware.startup_check(token)

print("\n=== Testing get_delivery_performance (scope granted) ===")
print(get_delivery_performance("SUP-019", "last_30_days"))
# Should show degradation_flag: True

print(get_delivery_performance("SUP-022", "last_30_days"))
# Should show degradation_flag: False

print(get_delivery_performance("SUP-999"))
# Should return SUPPLIER_NOT_FOUND error object

print("\n=== Testing knowledge_search (scope granted) ===")
print(knowledge_search("supplier delivery delay causing stockout"))
# Should return 2 relevant documents with similarity scores

print(knowledge_search("return rate size chart update"))
# Should return SOP and past case about size charts

print(knowledge_search(""))
# Should return EMPTY_QUERY error

print("\n=== Testing scope enforcement (token missing a required scope) ===")
narrow_token = pyjwt.encode(
    {"sub": "rod-service", "scopes": ["read:suppliers"], "exp": int(time.time()) + 3600},
    os.environ["MCP_JWT_SECRET"],
    algorithm="HS256",
)
auth_middleware.startup_check(narrow_token)
print(knowledge_search("anything"))
# Should return a MISSING_SCOPE error dict — token has read:suppliers but not read:knowledge
