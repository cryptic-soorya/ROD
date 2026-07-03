#!/usr/bin/env bash
# find_generate_token_callsites.sh
#
# Run from repo root. Finds every call site of the old generate_token()
# so you can manually route each one to generate_user_token() or
# generate_agent_token().

echo "== Import statements referencing generate_token =="
grep -rn --include="*.py" -E "import.*generate_token|from.*jwt_handler import" . 

echo
echo "== Call sites of generate_token( =="
grep -rn --include="*.py" -E "generate_token\s*\(" .

echo
echo "------------------------------------------------------------"
echo "For each call site above, decide:"
echo "  - human/user session token  -> generate_user_token(user_id, scopes[, expires_in_minutes])"
echo "  - agent/service token       -> generate_agent_token(agent_id, scopes)   # no expiry param"
echo "------------------------------------------------------------"