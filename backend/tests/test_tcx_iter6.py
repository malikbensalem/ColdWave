"""Iteration 6 — 3CX bug-fix verification.

Verifies:
  - POST /api/settings/integrations/tcx/test SUCCEEDS with real creds when
    tcx_url is saved WITHOUT a scheme (citiq.3cx.co.za:5001) and also with https://.
  - POST /api/calls/dial guards:
      * 400 when 3CX disabled/missing
      * 400 when contact is opted_out / do_not_call
    (We never actually place a successful outbound call.)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend/.env
    try:
        for line in open("/app/frontend/.env"):
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break
    except FileNotFoundError:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}

TCX_URL_NO_SCHEME = "citiq.3cx.co.za:5001"
TCX_URL_WITH_SCHEME = "https://citiq.3cx.co.za:5001"
TCX_EXT = "1019"
TCX_USER = "45214521"
TCX_PASS = "94qyLmZIzY1VABX4io9NKaR9iwO69Scu"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return s


def _get_integrations(s):
    r = s.get(f"{BASE_URL}/api/settings/integrations", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _put_integrations(s, integ):
    r = s.put(f"{BASE_URL}/api/settings/integrations", json=integ, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- 3CX Test Connection ----------------

class TestTcxConnection:
    def test_save_then_test_without_scheme(self, admin_session):
        integ = _get_integrations(admin_session)
        integ.update({
            "tcx_url": TCX_URL_NO_SCHEME,  # NO scheme — the bug
            "tcx_username": TCX_USER,
            "tcx_password": TCX_PASS,
            "tcx_extension": TCX_EXT,
            "tcx_enabled": True,
            "tcx_verify_tls": True,
        })
        _put_integrations(admin_session, integ)

        r = admin_session.post(f"{BASE_URL}/api/settings/integrations/tcx/test", timeout=45)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("extension") == TCX_EXT
        assert isinstance(data.get("device_count"), int)
        assert data["device_count"] >= 1, f"Expected >=1 device, got {data.get('device_count')}: {data.get('message')}"
        assert "Connected to 3CX" in data.get("message", "")

    def test_save_then_test_with_https_scheme(self, admin_session):
        integ = _get_integrations(admin_session)
        integ.update({
            "tcx_url": TCX_URL_WITH_SCHEME,
            "tcx_username": TCX_USER,
            "tcx_password": TCX_PASS,
            "tcx_extension": TCX_EXT,
            "tcx_enabled": True,
            "tcx_verify_tls": True,
        })
        _put_integrations(admin_session, integ)

        r = admin_session.post(f"{BASE_URL}/api/settings/integrations/tcx/test", timeout=45)
        assert r.status_code == 200, f"Expected 200 with https scheme, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("extension") == TCX_EXT
        assert data.get("device_count", 0) >= 1

    def test_missing_url_returns_400(self, admin_session):
        # Save without URL
        integ = _get_integrations(admin_session)
        saved = dict(integ)
        integ_no_url = dict(integ)
        integ_no_url["tcx_url"] = ""
        _put_integrations(admin_session, integ_no_url)
        try:
            r = admin_session.post(f"{BASE_URL}/api/settings/integrations/tcx/test", timeout=15)
            assert r.status_code == 400, f"Expected 400 with missing URL, got {r.status_code}: {r.text}"
        finally:
            # Restore the real creds (no scheme) for subsequent tests
            _put_integrations(admin_session, saved)


# ---------------- /api/calls/dial guards ----------------

class TestDialGuards:
    def test_dial_blocked_when_3cx_disabled(self, admin_session):
        integ = _get_integrations(admin_session)
        saved = dict(integ)
        disabled = dict(integ)
        disabled["tcx_enabled"] = False
        _put_integrations(admin_session, disabled)
        try:
            r = admin_session.post(f"{BASE_URL}/api/calls/dial", json={"destination": "+27000000000"}, timeout=15)
            assert r.status_code == 400, f"Expected 400 when 3CX disabled, got {r.status_code}: {r.text}"
            assert "not enabled" in r.text.lower() or "3cx" in r.text.lower()
        finally:
            _put_integrations(admin_session, saved)

    def test_dial_blocked_when_contact_opted_out(self, admin_session):
        # Ensure 3CX is enabled with real creds (no scheme) — set explicitly
        integ = _get_integrations(admin_session)
        integ.update({
            "tcx_url": TCX_URL_NO_SCHEME,
            "tcx_username": TCX_USER,
            "tcx_password": TCX_PASS,
            "tcx_extension": TCX_EXT,
            "tcx_enabled": True,
            "tcx_verify_tls": True,
        })
        _put_integrations(admin_session, integ)

        # Find an opted-out contact (the seeded "Daniel Cole" or any opted_out=true)
        r = admin_session.get(f"{BASE_URL}/api/contacts", timeout=15)
        assert r.status_code == 200, r.text
        contacts = r.json()
        opted = next((c for c in contacts if c.get("opted_out") or c.get("do_not_call")
                      or c.get("status") in ("opted_out", "dnc")), None)
        if not opted:
            # Create a temporary opted-out contact for the test
            payload = {
                "name": "TEST_OptedOut_Tester",
                "phone": "+27000000001",
                "email": "TEST_optedout@example.com",
                "opted_out": True,
            }
            cr = admin_session.post(f"{BASE_URL}/api/contacts", json=payload, timeout=15)
            assert cr.status_code in (200, 201), cr.text
            opted = cr.json()
            cleanup_id = opted.get("id")
        else:
            cleanup_id = None

        try:
            r = admin_session.post(f"{BASE_URL}/api/calls/dial",
                                   json={"contact_id": opted["id"]}, timeout=15)
            assert r.status_code == 400, f"Expected 400 for opted-out contact, got {r.status_code}: {r.text}"
            assert "opt" in r.text.lower() or "do not call" in r.text.lower() or "dnc" in r.text.lower()
        finally:
            if cleanup_id:
                admin_session.delete(f"{BASE_URL}/api/contacts/{cleanup_id}", timeout=10)
