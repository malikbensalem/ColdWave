"""
Iteration 8 regression: POST /api/settings/integrations/tcx/test must
1) Use the CURRENT form input values from the JSON body (no need to save first).
2) Fall back to the saved org config for unset fields (empty body still works).
3) Reject with 400 when the body provides an INCORRECT password
   (proving it truly used the body-provided value, not saved good creds).
"""
import os
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://dialflow-crm-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@coldwave.ai"
ADMIN_PASSWORD = "Admin123!"

# Live 3CX creds (Route Point) per review request
LIVE_TCX = {
    "tcx_url": "citiq.3cx.co.za:5001",
    "tcx_extension": "45214521",
    "tcx_username": "45214521",
    "tcx_password": "94qyLmZIzY1VABX4io9NKaR9iwO69Scu",
    "tcx_verify_tls": True,
}


# --- fixtures ---
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


# --- tests ---
def test_login_ok(admin_session):
    me = admin_session.get(f"{API}/auth/me", timeout=15)
    assert me.status_code == 200
    assert me.json().get("email") == ADMIN_EMAIL


def test_tcx_test_uses_current_body_values(admin_session):
    """PRIMARY: sending live creds in the body must succeed without a prior save."""
    r = admin_session.post(f"{API}/settings/integrations/tcx/test",
                           json=LIVE_TCX, timeout=30)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("ok") is True, body
    assert body.get("is_route_point") is True, body
    assert body.get("dn_type") == "Wroutepoint", body
    assert body.get("extension") == "45214521", body
    assert "Route Point" in (body.get("message") or ""), body


def test_tcx_test_empty_body_falls_back_to_saved(admin_session):
    """Empty JSON body must fall back to saved integration and succeed."""
    r = admin_session.post(f"{API}/settings/integrations/tcx/test",
                           json={}, timeout=30)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("ok") is True
    assert body.get("is_route_point") is True
    assert body.get("dn_type") == "Wroutepoint"


def test_tcx_test_wrong_password_in_body_returns_400(admin_session):
    """Sending a WRONG password in the body must be rejected — proves body is used."""
    bad = dict(LIVE_TCX, tcx_password="definitely-wrong-secret-xxx")
    r = admin_session.post(f"{API}/settings/integrations/tcx/test",
                           json=bad, timeout=30)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    detail = (r.json().get("detail") or "").lower()
    # accept any 3CX auth-style failure wording
    assert any(kw in detail for kw in ["auth", "unauthor", "invalid", "3cx", "credential", "token"]), detail


def test_tcx_test_requires_admin():
    """Anonymous caller must not be able to trigger the test endpoint."""
    r = requests.post(f"{API}/settings/integrations/tcx/test", json=LIVE_TCX, timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"
