"""
scripts/mint_token.py

Regenerates MCP_AUTH_TOKEN in rod/.env with a fresh agent service token.

Why this exists: generate_agent_token() hardcodes a 30-minute expiry
(auth/jwt_handler.py, SRS 2.1.2 non-negotiable), and main.py's startup hook
calls sys.exit() if MCP_AUTH_TOKEN has expired. So the backend needs a fresh
token minted before most restarts.

Run from the rod/ directory with the venv active:
    python scripts/mint_token.py
"""
import os
import re
import sys

from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
ENV_PATH = os.path.abspath(ENV_PATH)

# Must load .env BEFORE importing auth.jwt_handler — that module reads
# JWT_SECRET at import time via os.getenv(), and falls back silently to a
# dev default if the real secret isn't in the environment yet, which
# produces a token that fails signature verification against MCP_JWT_SECRET.
load_dotenv(dotenv_path=ENV_PATH)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth.jwt_handler import generate_agent_token, JWT_SECRET  # noqa: E402

AGENT_SCOPES = [
    "read:sales", "read:inventory", "read:returns", "read:customers",
    "read:promotions", "read:suppliers", "read:knowledge",
]


def main() -> None:
    mcp_secret = os.environ.get("MCP_JWT_SECRET", "")
    if JWT_SECRET != mcp_secret:
        sys.exit(
            "JWT_SECRET and MCP_JWT_SECRET don't match in .env — fix that "
            "before minting a token, or the backend will reject it at startup."
        )

    token = generate_agent_token("agent-service", AGENT_SCOPES)

    with open(ENV_PATH) as f:
        content = f.read()

    new_content, n = re.subn(
        r"^MCP_AUTH_TOKEN=.*$", f"MCP_AUTH_TOKEN={token}", content, flags=re.MULTILINE
    )
    if n != 1:
        sys.exit(f"expected exactly one MCP_AUTH_TOKEN= line in {ENV_PATH}, found {n}")

    with open(ENV_PATH, "w") as f:
        f.write(new_content)

    print(f"MCP_AUTH_TOKEN regenerated in {ENV_PATH} (valid for 30 minutes).")


if __name__ == "__main__":
    main()
