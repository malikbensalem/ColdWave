"""Iteration 17: GET /api/voices provider branching (ElevenLabs vs Inworld),
Telnyx/Inworld integration test endpoints, GET /api/inworld/voices."""
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}
TELNYX_KEY = "KEY01A02AE1DA6E357A07C29307F68079D6_uxiUETtktTV1AvGbvNRYS7"
TELNYX_CONN = "3032377320888337578"
INWORLD_KEY = "bjhFbHlXVGZhbTU3a29JN0dUX1I1S1RQVF9IOEtZX286cndCQXJKRlZ3OWVOakxCbVEzWmM0Tw=="


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    token = r.json().get("access_token")
    assert token, "no access_token in login response"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def original_integrations(client):
    r = client.get(f"{BASE_URL}/api/settings/integrations", timeout=30)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def set_provider(client, provider, extra=None):
    payload = {"tts_stt_provider": provider}
    if extra:
        payload.update(extra)
    r = client.put(f"{BASE_URL}/api/settings/integrations", json=payload, timeout=60)
    assert r.status_code == 200, f"PUT integrations failed {r.status_code}: {r.text[:300]}"
    return r.json()


class TestVoicesProviderBranching:
    def test_elevenlabs_shape(self, client, original_integrations):
        set_provider(client, "elevenlabs")
        r = client.get(f"{BASE_URL}/api/voices", timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        voices = data.get("voices")
        assert isinstance(voices, list) and len(voices) >= 5, data
        ids = [v["id"] for v in voices]
        assert "george" in ids, ids
        for v in voices:
            for k in ("id", "name", "gender", "accent", "display_name"):
                assert k in v, (k, v)
        assert data.get("provider") != "inworld"

    def test_inworld_shape(self, client):
        set_provider(client, "inworld", {"inworld_api_key": INWORLD_KEY})
        r = client.get(f"{BASE_URL}/api/voices", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("provider") == "inworld", data
        voices = data.get("voices")
        assert isinstance(voices, list) and len(voices) >= 20, f"only {len(voices or [])} voices; err={data.get('error')}"
        for v in voices[:10]:
            for k in ("id", "name", "gender", "accent", "display_name"):
                assert k in v, (k, v)
        assert data.get("source") == "inworld", data.get("source")

    def test_inworld_voices_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/inworld/voices", timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("source") == "inworld", data
        assert len(data.get("voices", [])) >= 20
        assert "voiceId" in data["voices"][0]

    def test_restore_original(self, client, original_integrations):
        prov = original_integrations.get("tts_stt_provider") or "elevenlabs"
        set_provider(client, prov)
        r = client.get(f"{BASE_URL}/api/settings/integrations", timeout=30)
        assert r.status_code == 200
        assert r.json().get("tts_stt_provider") == prov


class TestIntegrationKeyTests:
    def test_telnyx_test(self, client):
        r = client.post(f"{BASE_URL}/api/settings/integrations/telnyx/test",
                        json={"telnyx_api_key": TELNYX_KEY, "telnyx_connection_id": TELNYX_CONN}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("valid") is True, data

    def test_inworld_test(self, client):
        r = client.post(f"{BASE_URL}/api/settings/integrations/inworld/test",
                        json={"inworld_api_key": INWORLD_KEY}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("valid") is True, r.json()

    def test_inworld_test_bad_key(self, client):
        r = client.post(f"{BASE_URL}/api/settings/integrations/inworld/test",
                        json={"inworld_api_key": "bogus-key"}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("valid") is False, r.json()


class TestWarmCache:
    def test_warm_cache_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/campaigns", timeout=30)
        assert r.status_code == 200, r.text[:300]
        camps = r.json()
        camps = camps.get("campaigns", camps) if isinstance(camps, dict) else camps
        if not camps:
            pytest.skip("no campaigns available")
        cid = camps[0]["id"]
        r = client.post(f"{BASE_URL}/api/campaigns/{cid}/warm-cache", json={}, timeout=120)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert isinstance(r.json(), dict)
