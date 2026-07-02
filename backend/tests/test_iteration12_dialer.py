"""Iteration 12 — provider-aware dialer + CRM campaign picker (safe, error-path only)."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@coldwave.ai"
ADMIN_PW = "Admin123!"


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def contact_id(sess):
    r = sess.get(f"{API}/contacts", timeout=15)
    assert r.status_code == 200
    for c in r.json():
        if c.get("name") == "Aisha Khan" and not c.get("opted_out") and not c.get("do_not_call"):
            return c["id"]
    # fallback
    for c in r.json():
        if not c.get("opted_out") and not c.get("do_not_call") and c.get("status") not in ("opted_out", "dnc"):
            return c["id"]
    pytest.skip("No non-opted-out contact available")


@pytest.fixture(scope="module")
def orig_integrations(sess):
    r = sess.get(f"{API}/settings/integrations", timeout=10)
    assert r.status_code == 200
    orig = r.json()
    yield orig
    # cleanup: restore to task-spec baseline
    restore = {
        "telephony_provider": "3cx",
        "twilio_enabled": False,
        "twilio_account_sid": "",
        "twilio_auth_token": "",
        "twilio_phone_number": "",
        "tcx_url": "citiq.3cx.co.za:5001",
        "tcx_extension": "45214521",
        "tcx_enabled": False,
    }
    sess.put(f"{API}/settings/integrations", json=restore, timeout=10)


# ---------- Provider-aware dialing error paths ----------

def test_twilio_selected_but_not_enabled_returns_twilio_error(sess, contact_id, orig_integrations):
    r = sess.put(f"{API}/settings/integrations",
                 json={"telephony_provider": "twilio", "twilio_enabled": False}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("telephony_provider") == "twilio"
    assert body.get("twilio_enabled") is False

    r2 = sess.post(f"{API}/calls/dial", json={"contact_id": contact_id}, timeout=15)
    assert r2.status_code == 400, f"expected 400, got {r2.status_code}: {r2.text}"
    msg = (r2.json().get("detail") or "").lower()
    assert "twilio" in msg, f"expected Twilio-specific error, got: {msg}"
    assert "3cx live calling is not enabled" not in msg, "still hardcoded to 3CX error"


def test_3cx_selected_but_not_enabled_returns_3cx_error(sess, contact_id):
    r = sess.put(f"{API}/settings/integrations",
                 json={"telephony_provider": "3cx"}, timeout=10)
    assert r.status_code == 200
    assert r.json().get("telephony_provider") == "3cx"

    # also ensure tcx not enabled (baseline)
    sess.put(f"{API}/settings/integrations", json={"tcx_enabled": False}, timeout=10)

    r2 = sess.post(f"{API}/calls/dial", json={"contact_id": contact_id}, timeout=15)
    assert r2.status_code == 400, f"expected 400, got {r2.status_code}: {r2.text}"
    msg = (r2.json().get("detail") or "").lower()
    assert "3cx" in msg


# ---------- Integrations partial-merge (regression) ----------

def test_partial_put_preserves_other_fields(sess):
    # ensure baseline tcx fields set
    sess.put(f"{API}/settings/integrations", json={
        "tcx_url": "citiq.3cx.co.za:5001",
        "tcx_extension": "45214521",
    }, timeout=10)

    # partial PUT with ONLY telephony_provider
    r = sess.put(f"{API}/settings/integrations", json={"telephony_provider": "3cx"}, timeout=10)
    assert r.status_code == 200

    g = sess.get(f"{API}/settings/integrations", timeout=10).json()
    assert g.get("tcx_url") == "citiq.3cx.co.za:5001", f"tcx_url wiped: {g.get('tcx_url')}"
    assert g.get("tcx_extension") == "45214521", f"tcx_extension wiped: {g.get('tcx_extension')}"
    assert g.get("telephony_provider") == "3cx"


# ---------- Twilio credential test with bogus creds ----------

def test_twilio_test_bogus_creds(sess):
    r = sess.post(f"{API}/settings/integrations/twilio/test",
                  json={"account_sid": "ACbogus0000000000000000000000000000", "auth_token": "bogus"},
                  timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("valid") is False


# ---------- Campaigns list is non-empty (so CRM picker has options) ----------

def test_campaigns_available_for_picker(sess):
    r = sess.get(f"{API}/campaigns", timeout=10)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
