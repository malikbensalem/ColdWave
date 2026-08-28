"""Iteration 20 — Telnyx ConversationRelay (TeXML) switch + Twilio/LLM regression."""
import os
import re
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(client):
    r = client.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("access_token")
    assert tok, f"no access_token in {r.json()}"
    return tok


@pytest.fixture(scope="session")
def auth(client, token):
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture(scope="session")
def test_call_id(auth):
    """Start a browser test call to get a real call doc."""
    r = auth.post(f"{BASE_URL}/api/calls/test/start", json={}, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"test/start failed {r.status_code}: {r.text[:300]}")
    d = r.json()
    cid = d.get("call_id") or d.get("id")
    assert cid, f"no call id in {d}"
    return cid


# --- TeXML endpoints ---
class TestTexml:
    def test_texml_call_not_found(self, client):
        for method in ("get", "post"):
            r = getattr(requests, method)(f"{BASE_URL}/api/telephony/telnyx/texml/nonexistent-abc-123", timeout=30)
            assert r.status_code == 200, f"{method}: {r.status_code} {r.text[:200]}"
            assert "<Say>" in r.text and "<Hangup/>" in r.text, r.text[:300]
            assert "ConversationRelay" not in r.text

    def test_texml_conversationrelay_xml(self, test_call_id):
        r = requests.post(f"{BASE_URL}/api/telephony/telnyx/texml/{test_call_id}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        xml = r.text
        assert "<Connect" in xml and "action=" in xml
        assert "<ConversationRelay" in xml
        m = re.search(r'url="(wss://[^"]+)"', xml)
        assert m, xml[:500]
        assert m.group(1).endswith(f"/api/telephony/telnyx/relay/ws/{test_call_id}")
        assert "welcomeGreeting=" in xml
        assert 'transcriptionProvider="deepgram"' in xml
        assert re.search(r'voice="Telnyx\.[^"]+"', xml), xml[:500]
        assert 'interruptible="any"' in xml
        assert f'<Parameter name="call_id" value="{test_call_id}"' in xml

    def test_texml_ended(self, test_call_id):
        r = requests.post(f"{BASE_URL}/api/telephony/telnyx/texml/ended/{test_call_id}", timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert "<Response><Hangup/></Response>" in r.text.replace("\n", "")

    def test_texml_status_204(self, test_call_id):
        r = requests.post(f"{BASE_URL}/api/telephony/telnyx/texml/status/{test_call_id}",
                          data={"CallStatus": "ringing"}, timeout=30)
        assert r.status_code == 204, f"{r.status_code} {r.text[:200]}"
        r2 = requests.post(f"{BASE_URL}/api/telephony/telnyx/texml/status/unknown-id", timeout=30)
        assert r2.status_code == 204, f"{r2.status_code} {r2.text[:200]}"

    def test_texml_amd_204(self, test_call_id):
        r = requests.post(f"{BASE_URL}/api/telephony/telnyx/texml/amd/{test_call_id}",
                          data={"Result": "human"}, timeout=30)
        assert r.status_code == 204, f"{r.status_code} {r.text[:200]}"
        r2 = requests.post(f"{BASE_URL}/api/telephony/telnyx/texml/amd/unknown-id", timeout=30)
        assert r2.status_code == 204, f"{r2.status_code} {r2.text[:200]}"


# --- Telnyx key validation ---
class TestTelnyxValidate:
    def test_no_key_returns_invalid_not_500(self, auth):
        r = auth.post(f"{BASE_URL}/api/settings/integrations/telnyx/test", json={}, timeout=45)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("valid") is False, d
        assert d.get("error"), d

    def test_bad_key_returns_invalid(self, auth):
        r = auth.post(f"{BASE_URL}/api/settings/integrations/telnyx/test",
                      json={"telnyx_api_key": "KEYbogus123", "telnyx_texml_app_id": "123"}, timeout=45)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json().get("valid") is False, r.json()


# --- Settings persistence of new fields ---
class TestIntegrationFields:
    def test_new_telnyx_fields_persist(self, auth):
        g = auth.get(f"{BASE_URL}/api/settings/integrations", timeout=30)
        assert g.status_code == 200, g.text[:300]
        orig = g.json()
        payload = dict(orig)
        payload.update({"telnyx_texml_app_id": "TEST_app_1234",
                        "telnyx_tts_provider": "elevenlabs",
                        "telnyx_native_voice": "Telnyx.Natural.abbie"})
        p = auth.put(f"{BASE_URL}/api/settings/integrations", json=payload, timeout=30)
        assert p.status_code == 200, f"{p.status_code} {p.text[:300]}"
        g2 = auth.get(f"{BASE_URL}/api/settings/integrations", timeout=30)
        d = g2.json()
        assert d.get("telnyx_texml_app_id") == "TEST_app_1234", d
        assert d.get("telnyx_tts_provider") == "elevenlabs", d
        assert d.get("telnyx_native_voice") == "Telnyx.Natural.abbie", d
        # restore
        restore = dict(orig)
        restore.update({"telnyx_texml_app_id": orig.get("telnyx_texml_app_id") or "",
                        "telnyx_tts_provider": orig.get("telnyx_tts_provider") or "telnyx"})
        auth.put(f"{BASE_URL}/api/settings/integrations", json=restore, timeout=30)


# --- Regression: Twilio path + balances ---
class TestTwilioRegression:
    def test_twilio_relay_voice_unknown_call(self):
        for method in ("get", "post"):
            r = getattr(requests, method)(f"{BASE_URL}/api/telephony/twilio/relay/voice/nonexistent-xyz", timeout=30)
            assert r.status_code in (200, 403), f"{method}: {r.status_code} {r.text[:200]}"
            assert r.status_code != 500

    def test_twilio_relay_voice_existing_call(self, test_call_id):
        r = requests.post(f"{BASE_URL}/api/telephony/twilio/relay/voice/{test_call_id}", timeout=30)
        assert r.status_code in (200, 403), f"{r.status_code} {r.text[:200]}"
        if r.status_code == 200:
            assert "<Response" in r.text

    def test_balances(self, auth):
        r = auth.get(f"{BASE_URL}/api/settings/integrations/balances", timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), (list, dict))


# --- Regression: shared LLM turn loop ---
class TestTestCallLLM:
    def test_turn_returns_reply(self, auth, test_call_id):
        r = auth.post(f"{BASE_URL}/api/calls/test/turn",
                      json={"call_id": test_call_id, "message": "Hi, who is this?"}, timeout=120)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert isinstance(d.get("reply"), str) and d["reply"].strip(), d
