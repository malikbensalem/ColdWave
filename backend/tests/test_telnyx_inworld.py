"""Tests for the Telnyx (telephony) + Inworld (STT/TTS) provider option.

Covers:
1. Telnyx Ed25519 webhook signature validation (valid + invalid).
2. select_tts_provider / select_stt_provider resolution across provider combinations.
3. TTS cache hit/miss behaviour (Mongo-backed).
4. AMD/voicemail detection short-circuits the AI pipeline (telnyx_is_machine).

Mirrors the structure of test_twilio_voice_webhook.py / test_tts_selection.py.
Unit-level: no external network calls.
"""
import asyncio
import base64
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import integrations as I  # noqa: E402
from telnyx_voice import validate_telnyx_signature, telnyx_is_machine  # noqa: E402


# ---------------- 1. Telnyx Ed25519 signature ----------------
def _make_signed(public_key_b64=None):
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    ts = str(int(time.time()))
    raw = b'{"data":{"event_type":"call.answered"}}'
    signed = sk.sign((ts + "|").encode() + raw)
    sig_b64 = base64.b64encode(signed.signature).decode()
    headers = {"telnyx-signature-ed25519": sig_b64, "telnyx-timestamp": ts}
    return raw, headers, pub_b64


def test_telnyx_signature_valid():
    raw, headers, pub = _make_signed()
    assert validate_telnyx_signature(raw, headers, pub) is True


def test_telnyx_signature_invalid_wrong_key():
    raw, headers, _ = _make_signed()
    from nacl.signing import SigningKey
    other_pub = base64.b64encode(bytes(SigningKey.generate().verify_key)).decode()
    assert validate_telnyx_signature(raw, headers, other_pub) is False


def test_telnyx_signature_invalid_tampered_body():
    raw, headers, pub = _make_signed()
    assert validate_telnyx_signature(raw + b"tamper", headers, pub) is False


def test_telnyx_signature_stale_timestamp():
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    old_ts = str(int(time.time()) - 5000)
    raw = b'{"x":1}'
    sig = base64.b64encode(sk.sign((old_ts + "|").encode() + raw).signature).decode()
    headers = {"telnyx-signature-ed25519": sig, "telnyx-timestamp": old_ts}
    assert validate_telnyx_signature(raw, headers, pub, max_age=600) is False


# ---------------- 2. Provider selection ----------------
def test_select_tts_inworld_when_chosen_and_keyed():
    org = {"integrations": {"tts_stt_provider": "inworld", "inworld_api_key": "k"}}
    assert I.select_tts_provider(org)["provider"] == "inworld"


def test_select_tts_inworld_ignored_without_key():
    org = {"integrations": {"tts_stt_provider": "inworld"}}
    # No key -> should NOT resolve to inworld; falls through to elevenlabs/browser logic.
    assert I.select_tts_provider(org)["provider"] != "inworld"


def test_select_tts_elevenlabs_unchanged():
    org = {"integrations": {"elevenlabs_api_key": "abc", "elevenlabs_enabled": True}}
    assert I.select_tts_provider(org)["provider"] == "elevenlabs"


def test_select_tts_browser_when_selected():
    org = {"integrations": {"tts_stt_provider": "browser"}}
    assert I.select_tts_provider(org)["provider"] == "browser"


def test_select_stt_inworld_enabled():
    org = {"integrations": {"inworld_api_key": "k", "inworld_stt_enabled": True}}
    assert I.select_stt_provider(org)["provider"] == "inworld"


def test_select_stt_none_when_disabled():
    org = {"integrations": {"inworld_api_key": "k", "inworld_stt_enabled": False}}
    assert I.select_stt_provider(org)["provider"] == "none"


def test_select_stt_none_without_key():
    assert I.select_stt_provider({"integrations": {}})["provider"] == "none"


# ---------------- 3. TTS cache ----------------
def test_cache_key_deterministic_and_scoped():
    k1 = I._tts_cache_key("org1", "Ashley", "inworld-tts-2-flash", "Hello")
    k2 = I._tts_cache_key("org1", "Ashley", "inworld-tts-2-flash", "Hello")
    k3 = I._tts_cache_key("org2", "Ashley", "inworld-tts-2-flash", "Hello")
    assert k1 == k2 and k1 != k3


def test_cache_put_then_get_hit():
    async def run():
        from database import db
        org_id, vid, model, text = "cachetest", "Ashley", "inworld-tts-2-flash", "cache unit line"
        await db.tts_cache.delete_many({"org_id": org_id})
        miss = await I.tts_cache_get(org_id, vid, model, text)
        assert miss is None
        await I.tts_cache_put(org_id, vid, model, text, "QUJD", "mulaw_8000")
        hit = await I.tts_cache_get(org_id, vid, model, text)
        assert hit and hit["audio_b64"] == "QUJD" and hit["fmt"] == "mulaw_8000"
        await db.tts_cache.delete_many({"org_id": org_id})
    asyncio.get_event_loop().run_until_complete(run())


def test_generate_tts_inworld_no_key_errors_no_fallback():
    async def run():
        r = await I.generate_tts_inworld({"id": "x", "integrations": {}}, "hi", use_cache=False)
        assert r["provider"] == "inworld_error" and r["audio_b64"] is None and r["error"]
    asyncio.get_event_loop().run_until_complete(run())


# ---------------- 4. AMD short-circuit ----------------
@pytest.mark.parametrize("result,expected", [
    ("machine", True), ("fax", True), ("not_sure", True),
    ("machine_start", True), ("human", False), ("", False), ("human_residence", False),
])
def test_amd_short_circuit(result, expected):
    assert telnyx_is_machine(result) is expected
