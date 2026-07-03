"""
Tests for mcp_server/auth_middleware.py

Covers both layers documented in the module:
  - startup_check(token): missing/malformed/expired/bad-signature/alg=none
    tokens all raise SystemExit; a valid token caches its payload.
  - check_scope(token_payload, required_scope, tool_name): returns None on
    success, a structured error dict on failure, for both scope claim
    formats ("scope": "a b c" and "scopes": [...]), and the no-payload case.

auth_middleware keeps validated state in a module-level global
(_token_payload) set by startup_check, so each test resets it via the
reset_auth_state fixture to avoid cross-test leakage.
"""
import time

import jwt
import pytest

from mcp_server import auth_middleware as am


SECRET = "test-secret-do-not-use-in-prod-32bytes+"


@pytest.fixture(autouse=True)
def reset_auth_state(monkeypatch):
    """Ensure MCP_JWT_SECRET is set and _token_payload starts clean for every test."""
    monkeypatch.setenv(am.JWT_SECRET_ENV_VAR, SECRET)
    monkeypatch.setattr(am, "_token_payload", None)
    yield
    monkeypatch.setattr(am, "_token_payload", None)


def make_token(exp_delta=3600, scope="read:sales read:inventory", alg="HS256", key=SECRET, **extra_claims):
    payload = {"sub": "rod-service", "scope": scope, "exp": int(time.time()) + exp_delta, **extra_claims}
    return jwt.encode(payload, key, algorithm=alg)


# ── startup_check ──────────────────────────────────────────────────────────

class TestStartupCheck:
    def test_valid_token_succeeds_and_caches_payload(self):
        token = make_token()
        am.startup_check(token)  # should not raise
        payload = am.get_token_payload()
        assert payload is not None
        assert payload["sub"] == "rod-service"
        assert payload["scope"] == "read:sales read:inventory"

    def test_empty_token_raises_system_exit(self):
        with pytest.raises(SystemExit):
            am.startup_check("")

    def test_none_like_whitespace_token_raises_system_exit(self):
        with pytest.raises(SystemExit):
            am.startup_check("   ")

    def test_malformed_token_raises_system_exit(self):
        with pytest.raises(SystemExit):
            am.startup_check("not-a-real-jwt")

    def test_expired_token_raises_system_exit(self):
        token = make_token(exp_delta=-10)
        with pytest.raises(SystemExit):
            am.startup_check(token)

    def test_bad_signature_raises_system_exit(self):
        token = make_token(key="a-totally-different-secret")
        with pytest.raises(SystemExit):
            am.startup_check(token)

    def test_alg_none_forged_token_is_rejected(self):
        # Classic JWT vuln: a token claiming alg=none with no signature at all.
        # Must never be accepted, regardless of payload contents.
        forged = jwt.encode(
            {"sub": "attacker", "scope": "read:sales write:sales"},
            key=None,
            algorithm="none",
        )
        with pytest.raises(SystemExit):
            am.startup_check(forged)

    def test_missing_secret_env_var_raises_system_exit(self, monkeypatch):
        monkeypatch.delenv(am.JWT_SECRET_ENV_VAR, raising=False)
        token = make_token()
        with pytest.raises(SystemExit):
            am.startup_check(token)

    def test_failed_startup_check_does_not_cache_payload(self):
        token = make_token(exp_delta=-10)
        with pytest.raises(SystemExit):
            am.startup_check(token)
        assert am.get_token_payload() is None


# ── get_token_payload ──────────────────────────────────────────────────────

class TestGetTokenPayload:
    def test_returns_none_before_startup_check(self):
        assert am.get_token_payload() is None

    def test_returns_cached_payload_after_startup_check(self):
        am.startup_check(make_token(scope="read:sales"))
        assert am.get_token_payload()["scope"] == "read:sales"


# ── check_scope ────────────────────────────────────────────────────────────

class TestCheckScope:
    def test_scope_present_returns_none(self):
        payload = {"scope": "read:sales read:inventory"}
        assert am.check_scope(payload, "read:sales") is None

    def test_scope_missing_returns_error_dict(self):
        payload = {"scope": "read:sales"}
        err = am.check_scope(payload, "write:sales", tool_name="get_sales_data")
        assert err == {
            "error": "MISSING_SCOPE",
            "message": "Token does not grant required scope 'write:sales'.",
            "tool": "get_sales_data",
        }

    def test_tool_name_defaults_to_none_when_omitted(self):
        err = am.check_scope({"scope": "read:sales"}, "write:sales")
        assert err["tool"] is None

    def test_no_payload_returns_unauthenticated(self):
        err = am.check_scope(None, "read:sales", tool_name="get_sales_data")
        assert err["error"] == "UNAUTHENTICATED"
        assert err["tool"] == "get_sales_data"

    def test_empty_dict_payload_treated_as_unauthenticated(self):
        # {} is falsy in Python, same as None — check_scope can't distinguish
        # "decoded token with zero claims" from "no payload at all", so it
        # correctly treats both as UNAUTHENTICATED rather than MISSING_SCOPE.
        err = am.check_scope({}, "read:sales", tool_name="get_sales_data")
        assert err["error"] == "UNAUTHENTICATED"

    def test_scopes_as_list_form(self):
        payload = {"scopes": ["read:sales", "read:inventory"]}
        assert am.check_scope(payload, "read:inventory") is None

    def test_scopes_as_list_form_missing_scope(self):
        payload = {"scopes": ["read:sales"]}
        err = am.check_scope(payload, "write:sales")
        assert err["error"] == "MISSING_SCOPE"

    def test_both_scope_and_scopes_claims_combined(self):
        # If a token somehow has both claim styles, either should grant access.
        payload = {"scope": "read:sales", "scopes": ["read:inventory"]}
        assert am.check_scope(payload, "read:sales") is None
        assert am.check_scope(payload, "read:inventory") is None

    def test_never_raises_on_missing_scope(self):
        # check_scope's contract is return-a-dict, not raise. Confirm it
        # genuinely never raises for the failure cases above.
        try:
            am.check_scope(None, "read:sales")
            am.check_scope({}, "read:sales")
            am.check_scope({"scope": "read:inventory"}, "read:sales")
        except Exception as e:
            pytest.fail(f"check_scope raised unexpectedly: {e}")


# ── integration: startup_check → get_token_payload → check_scope ──────────

class TestFullFlow:
    def test_realistic_tool_call_flow_authorized(self):
        am.startup_check(make_token(scope="read:sales read:inventory"))
        err = am.check_scope(am.get_token_payload(), "read:sales", tool_name="get_sales_data")
        assert err is None

    def test_realistic_tool_call_flow_unauthorized(self):
        am.startup_check(make_token(scope="read:inventory"))  # no read:sales
        err = am.check_scope(am.get_token_payload(), "read:sales", tool_name="get_sales_data")
        assert err is not None
        assert err["error"] == "MISSING_SCOPE"
        assert err["tool"] == "get_sales_data"

    def test_token_never_appears_in_error_output(self):
        # Key constraint from the module docstring: the raw token must never
        # leak into any message, including error messages from failed checks.
        token = make_token(exp_delta=-10)
        with pytest.raises(SystemExit) as exc_info:
            am.startup_check(token)
        assert token not in str(exc_info.value)

        err = am.check_scope(None, "read:sales")
        assert token not in str(err)