"""
Iteration-2 integration tests against the live preview URL.
Covers: WhatsApp, ElevenLabs validate + Test Call, Audit log, KB opening mode, Health.
"""
import os
import re
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dialflow-crm-1.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@coldwave.ai"
ADMIN_PASSWORD = "Admin123!"
ELEVEN_KEY = "sk_fe1b8df9ee6a6f648241714c57f11edcf4558864c918271b"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# ---------- Health / Startup ----------
def test_health_endpoint():
    r = requests.get(f"{BASE_URL}/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert "services" in body and "api" in body["services"]


# ---------- WhatsApp ----------
def test_whatsapp_webhook_verification():
    r = requests.get(
        f"{BASE_URL}/api/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.challenge": "CHAL123", "hub.verify_token": "coldwave-verify-token"},
    )
    assert r.status_code == 200
    assert r.text.strip().strip('"') == "CHAL123"


def test_whatsapp_webhook_bad_token():
    r = requests.get(
        f"{BASE_URL}/api/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.challenge": "X", "hub.verify_token": "wrong"},
    )
    assert r.status_code in (401, 403)


def test_whatsapp_send_mock_delivered(session):
    r = session.post(f"{BASE_URL}/api/messages/whatsapp/send",
                     json={"to": "+447700900123", "body": "Hello from pytest"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("state") in ("queued", "sent", "delivered")
    mid = body.get("id") or body.get("message_id")
    assert mid
    # allow async simulation to advance
    time.sleep(1.2)
    lst = session.get(f"{BASE_URL}/api/messages", params={"channel": "whatsapp"})
    assert lst.status_code == 200
    rows = lst.json()
    assert isinstance(rows, list)
    found = [m for m in rows if m.get("to") == "+447700900123" or m.get("id") == mid]
    assert found, "sent message not appearing in /api/messages"


def test_whatsapp_send_blocked_by_dnc(session):
    # add to DNC
    dnc_no = "+15550009999"
    session.post(f"{BASE_URL}/api/compliance/dnc",
                 json={"phone": dnc_no, "reason": "test"})
    r = session.post(f"{BASE_URL}/api/messages/whatsapp/send",
                     json={"to": dnc_no, "body": "should be blocked"})
    assert r.status_code == 403, f"expected 403 for DNC, got {r.status_code} {r.text}"


def test_whatsapp_dead_letters_endpoint(session):
    r = session.get(f"{BASE_URL}/api/messages/dead-letters")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- ElevenLabs ----------
def test_elevenlabs_validate_valid_key(session):
    r = session.post(f"{BASE_URL}/api/settings/integrations/elevenlabs/test",
                     json={"api_key": ELEVEN_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("valid") is True
    assert isinstance(body.get("voice_count"), int) and body["voice_count"] > 0


def test_elevenlabs_validate_invalid_key(session):
    r = session.post(f"{BASE_URL}/api/settings/integrations/elevenlabs/test",
                     json={"api_key": "sk_invalid_xxx"})
    assert r.status_code == 200
    assert r.json().get("valid") is False


def test_elevenlabs_enable_and_test_call(session):
    # Save key + enable
    integ = session.get(f"{BASE_URL}/api/settings/integrations").json() or {}
    integ.update({"elevenlabs_api_key": ELEVEN_KEY, "elevenlabs_enabled": True})
    r = session.put(f"{BASE_URL}/api/settings/integrations", json=integ)
    assert r.status_code == 200
    # Start test call
    voices_resp = session.get(f"{BASE_URL}/api/voices").json()
    voices = voices_resp.get("voices") if isinstance(voices_resp, dict) else voices_resp
    assert voices, "no voices returned"
    vid = voices[0].get("voice_id") or voices[0].get("id")
    r2 = session.post(f"{BASE_URL}/api/calls/test/start",
                      json={"voice_id": vid, "phone": "+15551234567", "contact_name": "Tester"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body.get("tts_provider") == "elevenlabs", body
    assert body.get("audio_url"), "audio_url missing for elevenlabs call"
    # revert: clear key + disable
    integ.update({"elevenlabs_api_key": "", "elevenlabs_enabled": False})
    rr = session.put(f"{BASE_URL}/api/settings/integrations", json=integ)
    assert rr.status_code == 200


# ---------- Audit log ----------
def test_audit_entries_on_contact_create(session):
    payload = {"name": "TEST_audit_contact", "phone": "+15550101010", "email": "TEST_audit@example.com"}
    c = session.post(f"{BASE_URL}/api/contacts", json=payload)
    assert c.status_code in (200, 201), c.text
    cid = c.json().get("id")
    time.sleep(0.5)
    a = session.get(f"{BASE_URL}/api/audit", params={"entity": "contact"})
    assert a.status_code == 200
    rows = a.json()
    assert isinstance(rows, list) and rows
    sample = rows[0]
    assert sample.get("ip"), f"audit row missing ip: {sample}"
    assert sample.get("correlation_id"), f"audit row missing correlation_id: {sample}"
    created = sample.get("created_at") or ""
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", str(created)), f"created_at not ISO UTC: {created}"
    if cid:
        session.delete(f"{BASE_URL}/api/contacts/{cid}")


# ---------- KB opening mode ----------
def test_kb_create_and_opening_mode(session):
    # create KB entry
    kb = session.post(f"{BASE_URL}/api/kb",
                      json={"title": "TEST_Company FAQ", "content": "We are ColdWave, an AI calling SaaS. We help sales teams."})
    assert kb.status_code in (200, 201), kb.text
    kb_id = kb.json().get("id")
    # set opening mode = kb (PUT only allowed fields)
    upd = session.put(f"{BASE_URL}/api/settings/org",
                      json={"opening_mode": "kb", "opening_creativity": "medium"})
    assert upd.status_code == 200, upd.text
    # start test call
    voices_resp = session.get(f"{BASE_URL}/api/voices").json()
    voices = voices_resp.get("voices") if isinstance(voices_resp, dict) else voices_resp
    vid = voices[0].get("voice_id") or voices[0].get("id")
    r = session.post(f"{BASE_URL}/api/calls/test/start",
                     json={"voice_id": vid, "phone": "+15551234567", "contact_name": "Tester"})
    assert r.status_code == 200, r.text
    body = r.json()
    meta = body.get("opening_meta") or {}
    assert meta.get("mode") == "kb" or body.get("opening_mode") == "kb", f"opening_meta missing kb mode: {body}"
    # revert opening mode
    session.put(f"{BASE_URL}/api/settings/org", json={"opening_mode": "scripted"})
    if kb_id:
        session.delete(f"{BASE_URL}/api/kb/{kb_id}")
