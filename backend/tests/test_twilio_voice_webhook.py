"""Regression tests for the Twilio AI-voice webhook fix (iteration 13).

The bug: real Twilio calls with a campaign selected used to play a static
'this is an automated call from your AI assistant please hold' via the wrong
(Polly) voice, instead of running the same script/blueprint pipeline as Test Calls.

These tests verify:
1. /voice/{call_id} returns TwiML that speaks the call's opening (from script_content)
   AND a <Gather input="speech"> element for the turn loop.
2. /turn/{call_id} with an interested SpeechResult returns a contextual reply
   (mentions solar/price/quote/etc.) and another <Gather>.
3. /turn/{call_id} with an opt-out SpeechResult ends with <Hangup/> (no <Gather>).
4. /audio/<nonexistent>.mp3 returns 404 (endpoint wired).
5. /api/calls/dial with telephony_provider='twilio' and twilio_enabled=false
   returns 400 mentioning Twilio (NOT '3CX').
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest
import requests

# make backend imports work
BACKEND_DIR = "/app/backend"
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Load backend/.env so MONGO_URL / DB_NAME are available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_DIR, ".env"))
except Exception:
    pass

from database import db  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.strip().split("=", 1)[1].rstrip("/")
                break

CALL_ID = "qa_wh_call"
STATIC_PHRASE = "this is an automated call from your ai assistant please hold"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module", autouse=True)
def seed_call_doc():
    """Insert a test call document directly into Mongo; clean up at the end."""
    async def _setup():
        org = await db.organizations.find_one({}, {"_id": 0})
        assert org, "No organization found in DB"
        opening = "Hi, this is George from BrightSolar. Do you have a quick moment?"
        call_doc = {
            "id": CALL_ID,
            "org_id": org["id"],
            "voice_id": "george",
            "opening": opening,
            "transcript": [{"role": "agent", "content": opening, "ts": datetime.now(timezone.utc).isoformat()}],
            "script_content": "[OPENING] Hi, this is George from BrightSolar. Do you have a quick moment?\n[HOOK] We help homeowners cut energy bills with solar panels and free next-day installation.",
            "script_type": "line_by_line",
            "personality": "",
            "company_overview": "[About]\nBrightSolar installs solar panels with free next-day install. Typical quote is £4,000-£8,000 depending on roof size.",
            "provider": "twilio",
            "status": "initiating",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.calls.delete_one({"id": CALL_ID})
        await db.calls.insert_one(dict(call_doc))
        return org["id"]

    async def _teardown():
        await db.calls.delete_one({"id": CALL_ID})

    org_id = _run(_setup())
    yield org_id
    _run(_teardown())


# ------------------------------------------------------------------
# 1) VOICE webhook returns opening + <Gather>
# ------------------------------------------------------------------
class TestVoiceWebhook:
    def test_voice_webhook_post_returns_opening_and_gather(self, seed_call_doc):
        r = requests.post(f"{BASE_URL}/api/telephony/twilio/voice/{CALL_ID}", timeout=15)
        assert r.status_code == 200, r.text
        body = r.text
        # Must be TwiML
        assert "<Response" in body and "</Response>" in body
        # Opening line from script must be present (script-driven, not static Polly message)
        assert "BrightSolar" in body, f"Opening line not spoken. Body: {body[:400]}"
        assert "George" in body
        # Must NOT contain the old hardcoded static text
        assert STATIC_PHRASE not in body.lower(), "Static AI-assistant phrase still present!"
        # Must contain a <Gather input="speech"> to drive turn loop
        assert '<Gather input="speech"' in body, "No speech Gather in TwiML"

    def test_voice_webhook_get_also_works(self, seed_call_doc):
        r = requests.get(f"{BASE_URL}/api/telephony/twilio/voice/{CALL_ID}", timeout=15)
        assert r.status_code == 200
        assert "BrightSolar" in r.text
        assert '<Gather input="speech"' in r.text


# ------------------------------------------------------------------
# 2) TURN webhook produces contextual AI reply
# ------------------------------------------------------------------
class TestTurnWebhook:
    def test_turn_interested_returns_contextual_reply_and_gather(self, seed_call_doc):
        r = requests.post(
            f"{BASE_URL}/api/telephony/twilio/turn/{CALL_ID}",
            data={"SpeechResult": "Yes I am interested, how much does it cost?"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.text.lower()
        assert "<response" in body and "</response>" in body
        # Contextual reply should touch on the campaign topic (solar / price / quote)
        contextual_hit = any(k in body for k in ("solar", "price", "quote", "cost", "energy", "install", "brightsolar", "£"))
        assert contextual_hit, f"Reply does not appear contextual to script/company. Body: {r.text[:600]}"
        # Loop continues → another Gather
        assert '<gather input="speech"' in body, "Expected another Gather after AI reply"
        # Definitely no static Polly greeting
        assert STATIC_PHRASE not in body

    def test_turn_opt_out_hangs_up(self, seed_call_doc):
        r = requests.post(
            f"{BASE_URL}/api/telephony/twilio/turn/{CALL_ID}",
            data={"SpeechResult": "Not interested, remove me from your list"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.text.lower()
        assert "<hangup/>" in body, f"Opt-out did not hang up. Body: {r.text[:600]}"
        assert '<gather input="speech"' not in body, "Should not gather again after opt-out"


# ------------------------------------------------------------------
# 3) Audio endpoint wired
# ------------------------------------------------------------------
class TestAudioEndpoint:
    def test_audio_unknown_token_returns_404(self):
        r = requests.get(f"{BASE_URL}/api/telephony/twilio/audio/does_not_exist.mp3", timeout=10)
        assert r.status_code == 404


# ------------------------------------------------------------------
# 4) Provider routing: Twilio-selected but not enabled → 400 mentioning Twilio
# ------------------------------------------------------------------
class TestProviderRoutingGuard:
    def test_dial_with_twilio_selected_but_disabled_returns_twilio_400(self):
        s = requests.Session()
        # Login as admin (cookie-based auth)
        login = s.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@coldwave.ai", "password": "Admin123!"}, timeout=15)
        assert login.status_code == 200, f"Admin login failed: {login.status_code} {login.text}"

        # Read current integrations to restore later
        cur = s.get(f"{BASE_URL}/api/settings/integrations", timeout=15)
        assert cur.status_code == 200, cur.text
        original = cur.json()
        original_provider = original.get("telephony_provider", "3cx")

        try:
            # Switch to Twilio selected but not enabled
            upd = s.put(f"{BASE_URL}/api/settings/integrations",
                        json={"telephony_provider": "twilio", "twilio_enabled": False}, timeout=15)
            assert upd.status_code == 200, upd.text

            # Find a valid non-opted-out contact
            # Use CRM list endpoint
            contacts = s.get(f"{BASE_URL}/api/contacts", timeout=15)
            assert contacts.status_code == 200, contacts.text
            usable = [c for c in contacts.json()
                      if c.get("phone") and not c.get("opted_out") and not c.get("do_not_call")]
            assert usable, "No usable contact in demo org for guard test"
            contact_id = usable[0]["id"]

            # POST /api/calls/dial — expect 400 mentioning TWILIO (not 3CX)
            r = s.post(f"{BASE_URL}/api/calls/dial",
                       json={"contact_id": contact_id}, timeout=15)
            assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
            msg = r.text.lower()
            assert "twilio" in msg, f"Error should mention Twilio: {r.text}"
            assert "3cx" not in msg, f"Error should NOT mention 3CX (wrong routing): {r.text}"
        finally:
            # Restore telephony_provider (and twilio_enabled state) as required by task
            s.put(f"{BASE_URL}/api/settings/integrations",
                  json={"telephony_provider": original_provider,
                        "twilio_enabled": bool(original.get("twilio_enabled", False))}, timeout=15)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
