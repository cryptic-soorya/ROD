"""
tests/conftest.py

Only main.py and scripts/mint_token.py call load_dotenv() — pytest never
does, so agent/react_loop.py's module-level _load_gemini_keys() raises
RuntimeError at collection time (no GEMINI_API_KEY_* in the environment)
and test_react_loop.py fails to even import. Loading .env here, before any
test module is collected, fixes that the same way main.py fixes it for the
running app.

(The Gemini client-pool rotation mismatch in test_react_loop.py — tests
patch _client / _CLIENTS[0] but _call_gemini_with_retry rotates across the
whole pool — is fixed locally in that test file, not here, since it's
specific to how those tests mock the Gemini boundary.)
"""
from dotenv import load_dotenv

load_dotenv()
