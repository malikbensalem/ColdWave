"""Iteration 7 — Bug fix regression for 3CX Route Point direct dial.

NOTE: This file intentionally places EXACTLY ONE live outbound call via
POST /api/calls/dial to +27625058013 to prove the call dials the client
directly (not the agent extension). All other tests are read-only or
exercise guards that never reach the telephony layer.
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dialflow-crm-1.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@coldwave.ai"
ADMIN_PASSWORD = "Admin123!"
LIVE_NUMBER = "+27625058013"
EXPECTED_DN = "45214521"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ---------- TCX test connection: must confirm Route Point ----------
def test_tcx_test_connection_reports_route_point(admin_session):
    r = admin_session.post(f"{BASE_URL}/api/settings/integrations/tcx/test", timeout=60)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True, body
    assert body.get("is_route_point") is True, f"is_route_point should be True, got: {body}"
    dn_type = str(body.get("dn_type", "")).lower()
    assert "routepoint" in dn_type, f"dn_type should mention routepoint, got: {body.get('dn_type')}"
    assert "Route Point" in body.get("message", ""), f"message should mention Route Point: {body.get('message')}"
    assert "ready for direct automated outbound calls" in body.get("message", ""), body.get("message")
    assert str(body.get("extension")) == EXPECTED_DN, f"Expected DN {EXPECTED_DN}, got {body.get('extension')}"


# ---------- Guards ----------
def test_dial_guard_empty_destination_no_contact(admin_session):
    r = admin_session.post(f"{BASE_URL}/api/calls/dial", json={"destination": ""}, timeout=30)
    assert r.status_code == 400, f"Expected 400 for empty destination, got {r.status_code}: {r.text[:200]}"


def test_dial_guard_opted_out_contact_returns_400(admin_session):
    # Find an opted-out contact (Daniel Cole is pre-seeded as opted_out)
    r = admin_session.get(f"{BASE_URL}/api/contacts", timeout=30)
    assert r.status_code == 200
    contacts = r.json()
    opted = next((c for c in contacts if c.get("opted_out") or c.get("status") == "opted_out" or c.get("status") == "dnc"), None)
    assert opted is not None, "Expected at least one opted_out/dnc contact in seed data"
    r2 = admin_session.post(f"{BASE_URL}/api/calls/dial", json={"contact_id": opted["id"]}, timeout=30)
    assert r2.status_code == 400, f"Expected 400 for opted-out contact, got {r2.status_code}: {r2.text[:200]}"
    msg = r2.json().get("detail", "").lower()
    assert "opt" in msg or "do not call" in msg or "dnc" in msg, f"Error msg should mention opt-out: {msg}"


# ---------- THE BUG FIX: single live dial to the client number ----------
def test_dial_places_direct_call_to_client_number(admin_session):
    """PLACES A LIVE OUTBOUND CALL — runs exactly once.

    Verifies the regression: the call destination must be the CLIENT number
    (+27625058013), NOT the agent extension '1019' and NOT the route point
    '45214521'. This proves the DN-level Route-Point origination dials the
    client directly (no human leg).
    """
    r = admin_session.post(f"{BASE_URL}/api/calls/dial", json={"destination": LIVE_NUMBER}, timeout=60)
    assert r.status_code == 200, f"Dial failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True, f"ok should be True, got: {body}"
    status = str(body.get("status", ""))
    assert status, f"status missing: {body}"
    # Status should indicate the call was initiated (not a failure word)
    assert any(k in status.lower() for k in ("dial", "init", "ring", "connect", "ok")), f"Unexpected status: {status}"
    assert body.get("callid"), f"callid missing: {body}"
    call = body.get("call") or {}
    # CRITICAL ASSERTIONS: destination must be the client number, NOT 1019 or the route point
    assert call.get("destination") == LIVE_NUMBER, (
        f"REGRESSION! destination should be client number {LIVE_NUMBER}, "
        f"got {call.get('destination')!r}. Full call: {call}"
    )
    assert call.get("destination") != "1019", "Destination must NOT be the old agent extension 1019"
    assert call.get("destination") != EXPECTED_DN, "Destination must NOT be the Route Point DN itself"
    assert call.get("provider") == "3cx"
    assert call.get("callid") == body.get("callid")
