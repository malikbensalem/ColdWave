"""Iteration 14: Twilio ConversationRelay streaming, Live Calls monitoring,
human takeover, hangup, and voice_mode persistence."""
import os
import pytest
import requests
from pathlib import Path

_env = Path("/app/frontend/.env").read_text()
for _line in _env.splitlines():
    if _line.startswith("REACT_APP_BACKEND_URL="):
        os.environ["REACT_APP_BACKEND_URL"] = _line.split("=", 1)[1].strip()
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "admin@coldwave.ai", "password": "Admin123!"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Live calls list ----------
def test_live_calls_active_returns_list(h):
    r = requests.get(f"{API}/calls/live/active", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    # No is_test calls should be included
    for c in data:
        assert c.get("is_test") is not True


# ---------- Relay TwiML endpoint (no auth) ----------
def test_relay_voice_nonexistent_returns_hangup_twiml():
    r = requests.post(f"{API}/telephony/twilio/relay/voice/does_not_exist", timeout=15)
    assert r.status_code == 200
    assert "application/xml" in r.headers.get("content-type", "")
    body = r.text
    assert "<Response>" in body and "<Hangup" in body and "could not be set up" in body


def test_relay_voice_existing_call_returns_conversation_relay(h):
    # Seed a fake Twilio call
    call_id = "call_test_relay_it14"
    org_id = None
    # Find org via /settings/org
    r = requests.get(f"{API}/settings/org", headers=h, timeout=15)
    assert r.status_code == 200
    org_id = r.json()["id"]
    # Use raw db via /calls test seeding? None available — instead create via /calls/test/start
    # That marks is_test=True. Relay endpoint just looks up id; is_test doesn't matter.
    r = requests.post(f"{API}/calls/test/start", headers=h, json={}, timeout=30)
    assert r.status_code == 200, r.text
    cid = r.json()["call_id"]
    r = requests.post(f"{API}/telephony/twilio/relay/voice/{cid}", timeout=15)
    assert r.status_code == 200
    body = r.text
    assert "<Connect>" in body and "<ConversationRelay" in body
    assert "url=" in body and "/api/telephony/twilio/relay/ws/" + cid in body


# ---------- Takeover guards ----------
def test_takeover_404_when_call_missing(h):
    r = requests.post(f"{API}/calls/nope_missing/takeover",
                      headers=h, json={"human_number": "+441234567890"}, timeout=15)
    assert r.status_code == 404


def test_takeover_400_for_non_twilio_call(h):
    # Find any existing non-twilio call in the org
    r = requests.get(f"{API}/calls/live/active", headers=h, timeout=15)
    calls = r.json()
    target = next((c for c in calls if c.get("provider") != "twilio"), None)
    if not target:
        # Also try full calls list
        r2 = requests.get(f"{API}/calls", headers=h, timeout=15)
        calls2 = r2.json()
        target = next((c for c in calls2 if c.get("provider") == "3cx"), None)
    if not target:
        pytest.skip("No 3cx call available to test takeover guard")
    r3 = requests.post(f"{API}/calls/{target['id']}/takeover",
                       headers=h, json={"human_number": "+441234567890"}, timeout=15)
    assert r3.status_code == 400
    msg = r3.json().get("detail", "").lower()
    assert "twilio" in msg or "active" in msg


def test_takeover_missing_human_number_returns_422_or_400(h):
    # 422 from pydantic when field missing
    r = requests.post(f"{API}/calls/anything/takeover", headers=h, json={}, timeout=15)
    assert r.status_code in (400, 422)


# ---------- Hangup guards ----------
def test_hangup_404_when_call_missing(h):
    r = requests.post(f"{API}/calls/nope_missing/hangup", headers=h, timeout=15)
    assert r.status_code == 404


def test_hangup_400_for_non_twilio_call(h):
    r = requests.get(f"{API}/calls", headers=h, timeout=15)
    target = next((c for c in r.json() if c.get("provider") == "3cx"), None)
    if not target:
        pytest.skip("No 3cx call available to test hangup guard")
    r2 = requests.post(f"{API}/calls/{target['id']}/hangup", headers=h, timeout=15)
    assert r2.status_code == 400


# ---------- Voice mode persistence + partial merge regression ----------
def test_voice_mode_persist_and_partial_merge(h):
    # Get current
    r = requests.get(f"{API}/settings/integrations", headers=h, timeout=15)
    assert r.status_code == 200
    before = r.json()
    # Ensure some twilio fields have values to test non-wipe (set if empty)
    if not before.get("twilio_account_sid"):
        requests.put(f"{API}/settings/integrations", headers=h,
                     json={"twilio_account_sid": "ACtest_sentinel_sid",
                           "twilio_phone_number": "+441111111111"}, timeout=15)
    # PUT partial with only voice mode = gather
    r2 = requests.put(f"{API}/settings/integrations", headers=h,
                      json={"twilio_voice_mode": "gather"}, timeout=15)
    assert r2.status_code == 200, r2.text
    r3 = requests.get(f"{API}/settings/integrations", headers=h, timeout=15)
    got = r3.json()
    assert got.get("twilio_voice_mode") == "gather"
    # Other twilio fields still present (not wiped)
    assert got.get("twilio_account_sid"), "twilio_account_sid was wiped by partial PUT"
    assert got.get("twilio_phone_number"), "twilio_phone_number was wiped by partial PUT"
    # Set back to stream
    r4 = requests.put(f"{API}/settings/integrations", headers=h,
                      json={"twilio_voice_mode": "stream"}, timeout=15)
    assert r4.status_code == 200
    r5 = requests.get(f"{API}/settings/integrations", headers=h, timeout=15)
    assert r5.json().get("twilio_voice_mode") == "stream"
