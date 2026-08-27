"""Iteration 19 — verify the Telnyx balance row APPEARS once a telnyx api key is saved.

Uses a deliberately invalid sentinel key so the row must come back ok=false with a
clear 'Invalid Telnyx API key.' detail (never a 500). Restores the original value.
"""
import os

import pytest
import requests
from dotenv import dotenv_values

B = (os.environ.get("REACT_APP_BACKEND_URL")
     or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
SENTINEL = "KEY_TEST_invalid_telnyx_sentinel"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{B}/api/auth/login",
               json={"email": "admin@coldwave.ai", "password": "Admin123!"}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.fixture(scope="module")
def telnyx_key_saved(client):
    before = client.get(f"{B}/api/settings/integrations", timeout=30).json()
    orig = before.get("telnyx_api_key", "")
    r = client.put(f"{B}/api/settings/integrations", json={"telnyx_api_key": SENTINEL}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    yield
    r = client.put(f"{B}/api/settings/integrations", json={"telnyx_api_key": orig}, timeout=30)
    assert r.status_code == 200
    after = client.get(f"{B}/api/settings/integrations", timeout=30).json()
    assert after.get("telnyx_api_key", "") == orig, "failed to restore original telnyx key"


def _items(resp):
    body = resp.json()
    return body if isinstance(body, list) else body.get("balances", body.get("items"))


def test_telnyx_row_appears_and_reports_invalid_key(client, telnyx_key_saved):
    r = client.get(f"{B}/api/settings/integrations/balances", timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
    items = _items(r)
    telnyx = [i for i in items if i["provider"] == "telnyx"]
    assert len(telnyx) == 1, f"telnyx row missing after saving a key: {items}"
    row = telnyx[0]
    assert row["label"] == "Telnyx"
    assert row["unit"] == "balance"
    assert row["ok"] is False
    assert row["detail"], "invalid key must produce a human readable detail"
    # ElevenLabs / Twilio rows unaffected
    assert any(i["provider"] == "elevenlabs" for i in items)
