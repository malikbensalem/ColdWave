"""Iteration 18 — retest of the Inworld TTS critical bug fix + /api/voices regressions."""
import os
import time

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}
INWORLD_KEY = "bjhFbHlXVGZhbTU3a29JN0dUX1I1S1RQVF9IOEtZX286cndCQXJKRlZ3OWVOakxCbVEzWmM0Tw=="
TELNYX_KEY = "KEY01A02AE1DA6E357A07C29307F68079D6_uxiUETtktTV1AvGbvNRYS7"
TELNYX_CONN = "3032377320888337578"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("access_token")
    assert tok, "no access_token in login response"
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


def set_provider(client, provider):
    r = client.put(f"{BASE_URL}/api/settings/integrations", json={"tts_stt_provider": provider}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    return r


@pytest.fixture(scope="module", autouse=True)
def restore_inworld(client):
    yield
    set_provider(client, "inworld")


# ---------------- CRITICAL: warm-cache is now backgrounded & fast ----------------
class TestWarmCache:
    def test_warm_cache_returns_fast_and_warming(self, client):
        set_provider(client, "inworld")
        camps = client.get(f"{BASE_URL}/api/campaigns", timeout=30).json()
        camps = camps if isinstance(camps, list) else camps.get("campaigns", [])
        assert camps, "no campaigns to test"
        cid = camps[0]["id"]
        print(f"campaign {cid} voice_id={camps[0].get('voice_id')}")
        t0 = time.time()
        r = client.post(f"{BASE_URL}/api/campaigns/{cid}/warm-cache", timeout=60)
        dt = time.time() - t0
        print(f"warm-cache status={r.status_code} t={dt:.2f}s body={r.text[:200]}")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("status") == "warming"
        assert dt < 2.0, f"warm-cache took {dt:.2f}s, expected <2s (background task)"

    def test_warm_cache_second_call_also_fast(self, client):
        camps = client.get(f"{BASE_URL}/api/campaigns", timeout=30).json()
        camps = camps if isinstance(camps, list) else camps.get("campaigns", [])
        cid = camps[0]["id"]
        time.sleep(12)  # let the background warm finish
        t0 = time.time()
        r = client.post(f"{BASE_URL}/api/campaigns/{cid}/warm-cache", timeout=60)
        dt = time.time() - t0
        assert r.status_code == 200 and r.json().get("status") == "warming"
        assert dt < 2.0


# ---------------- REGRESSION: /api/voices provider branching ----------------
class TestVoices:
    def test_voices_inworld_branch(self, client):
        set_provider(client, "inworld")
        r = client.get(f"{BASE_URL}/api/voices", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("provider") == "inworld", d.get("provider")
        voices = d["voices"]
        assert len(voices) > 50, f"only {len(voices)} inworld voices"
        v = voices[0]
        for k in ("id", "name", "gender", "accent", "display_name", "provider"):
            assert k in v, f"missing {k} in {v}"
        assert v["provider"] == "inworld"
        print(f"inworld voices={len(voices)} sample={v['id']}")

    def test_voices_elevenlabs_branch(self, client):
        set_provider(client, "elevenlabs")
        r = client.get(f"{BASE_URL}/api/voices", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d.get("provider") == "elevenlabs", d.get("provider")
        ids = [v["id"] for v in d["voices"]]
        assert "george" in ids, ids
        assert len([v for v in d["voices"] if not v.get("is_custom")]) == 12, len(ids)
        for v in d["voices"]:
            if not v.get("is_custom"):
                assert v.get("provider") == "elevenlabs", v
        print(f"elevenlabs voices={len(ids)}")
        set_provider(client, "inworld")


# ---------------- REGRESSION: integration test endpoints ----------------
class TestIntegrationTests:
    def test_inworld_test(self, client):
        r = client.post(f"{BASE_URL}/api/settings/integrations/inworld/test",
                        json={"api_key": INWORLD_KEY}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        print("inworld/test:", d)
        assert d.get("valid") is True, d

    def test_telnyx_test(self, client):
        r = client.post(f"{BASE_URL}/api/settings/integrations/telnyx/test",
                        json={"telnyx_api_key": TELNYX_KEY, "telnyx_connection_id": TELNYX_CONN}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        print("telnyx/test:", d)
        assert d.get("valid") is True, d

    def test_inworld_voices_dynamic(self, client):
        r = client.get(f"{BASE_URL}/api/inworld/voices", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert len(d.get("voices", [])) > 50, d.get("error")
        assert d["voices"][0].get("voiceId")
        print(f"inworld/voices={len(d['voices'])} source={d.get('source')}")
