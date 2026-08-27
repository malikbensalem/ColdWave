"""Iteration 19 — Telnyx balance row, Inworld preview endpoint, provider-aware voice preview.

Scope (per review request):
  * auth login (admin@coldwave.ai)
  * GET  /api/settings/integrations/balances  -> 200 list; telnyx row iff key configured
  * POST /api/inworld/preview                 -> 200 {audio_url, error}, never 500
  * POST /api/voices/preview                  -> 200, 'mock' bool for elevenlabs provider
  * GET  /api/voices                          -> 200 with top-level 'provider'
"""
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


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("access_token")
    if not tok:
        pytest.fail(f"no access_token in login response: {r.text[:300]}")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def integrations(client):
    r = client.get(f"{BASE_URL}/api/settings/integrations", timeout=30)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# --- auth ---
class TestAuth:
    def test_login_and_me(self, client):
        r = client.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["email"] == ADMIN["email"]
        assert d.get("role") in ("admin", "owner")


# --- balances ---
class TestBalances:
    def test_balances_returns_list(self, client, integrations):
        r = client.get(f"{BASE_URL}/api/settings/integrations/balances", timeout=60)
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        items = body if isinstance(body, list) else body.get("balances", body.get("items"))
        assert isinstance(items, list), f"expected list, got {type(body)}: {str(body)[:200]}"
        for it in items:
            assert "provider" in it and "label" in it and "unit" in it
            assert "ok" in it and "detail" in it
            assert "_id" not in it

    def test_telnyx_row_presence_matches_key(self, client, integrations):
        r = client.get(f"{BASE_URL}/api/settings/integrations/balances", timeout=60)
        assert r.status_code == 200
        body = r.json()
        items = body if isinstance(body, list) else body.get("balances", body.get("items"))
        telnyx = [i for i in items if i["provider"] == "telnyx"]
        has_key = bool(integrations.get("telnyx_api_key"))
        if has_key:
            assert len(telnyx) == 1, "telnyx key configured but no telnyx balance row"
            assert telnyx[0]["unit"] == "balance"
            assert telnyx[0]["detail"], "telnyx row must carry a human-readable detail"
        else:
            assert telnyx == [], "telnyx row present without a configured key"

    def test_balances_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/settings/integrations/balances", timeout=30)
        assert r.status_code in (401, 403), r.status_code


# --- inworld preview ---
class TestInworldPreview:
    def test_preview_ashley_shape(self, client):
        r = client.post(f"{BASE_URL}/api/inworld/preview", json={"voice_id": "Ashley"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        d = r.json()
        assert set(["audio_url", "error"]).issubset(d.keys()), d
        if d["audio_url"]:
            assert d["audio_url"].startswith("data:audio/wav;base64,")
            assert d["error"] is None
        else:
            assert isinstance(d["error"], str) and d["error"].strip(), "no audio -> non-empty error required"

    def test_preview_no_voice_id(self, client):
        r = client.post(f"{BASE_URL}/api/inworld/preview", json={}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        # falls back to saved org voice; either audio or a clear error
        assert d["audio_url"] or (isinstance(d["error"], str) and d["error"].strip())

    def test_preview_bogus_voice_no_500(self, client):
        r = client.post(f"{BASE_URL}/api/inworld/preview",
                        json={"voice_id": "definitely_not_a_voice_xyz"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        d = r.json()
        if not d["audio_url"]:
            assert isinstance(d["error"], str) and d["error"].strip()

    def test_preview_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/inworld/preview", json={"voice_id": "Ashley"}, timeout=30)
        assert r.status_code in (401, 403)


# --- voices ---
class TestVoices:
    def test_voices_has_provider(self, client):
        r = client.get(f"{BASE_URL}/api/voices", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("provider") in ("elevenlabs", "inworld"), d.get("provider")
        assert isinstance(d.get("voices"), list) and len(d["voices"]) > 0
        assert all("id" in v and "name" in v for v in d["voices"][:5])

    def test_voice_preview_shape(self, client):
        r = client.post(f"{BASE_URL}/api/voices/preview",
                        json={"voice_id": "george", "text": "hello"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        d = r.json()
        assert isinstance(d.get("mock"), bool), d
        assert "provider" in d
        if not d.get("audio_url"):
            assert d.get("mock") is True or d.get("error")

    def test_voice_preview_uses_active_provider(self, client):
        v = client.get(f"{BASE_URL}/api/voices", timeout=60).json()
        prov = v["provider"]
        vid = v["voices"][0]["id"]
        r = client.post(f"{BASE_URL}/api/voices/preview",
                        json={"voice_id": vid, "text": "Testing one two three."}, timeout=90)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d.get("provider", "").startswith(prov) or d.get("provider") in ("mock", "browser", prov), d.get("provider")

    def test_voice_preview_empty_voice_id_no_500(self, client):
        r = client.post(f"{BASE_URL}/api/voices/preview", json={"text": "hi"}, timeout=60)
        assert r.status_code in (200, 422), f"{r.status_code}: {r.text[:300]}"
