"""
tests/conftest.py

Only main.py and scripts/mint_token.py call load_dotenv() — pytest never
does, so agent/graph.py's module-level _load_gemini_keys() raises
RuntimeError at collection time (no GEMINI_API_KEY_* in the environment)
and test_graph.py fails to even import. Loading .env here, before any
test module is collected, fixes that the same way main.py fixes it for the
running app.
"""
from dotenv import load_dotenv

load_dotenv()
