"""Unit tests for deterministic TTS provider selection and the ElevenLabs path.
These guard against regressions where test calls silently fall back to the browser
voice even though valid ElevenLabs credentials are configured.

Run: cd backend && python3 -m pytest tests/ -v
"""
import sys
import types
import asyncio
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import integrations  # noqa: E402


def _org(key="", enabled=False):
    return {"integrations": {"elevenlabs_api_key": key, "elevenlabs_enabled": enabled}}


def test_select_elevenlabs_when_key_and_enabled():
    sel = integrations.select_tts_provider(_org("sk_real", True))
    assert sel["provider"] == "elevenlabs"
    assert sel["reason"] == "valid_config"


def test_select_browser_when_key_present_but_disabled():
    sel = integrations.select_tts_provider(_org("sk_real", False))
    assert sel["provider"] == "browser"
    assert sel["reason"] == "elevenlabs_key_present_but_disabled"


def test_select_browser_when_no_key(monkeypatch):
    monkeypatch.setattr(os, "environ", {**os.environ, "ELEVENLABS_API_KEY": ""})
    sel = integrations.select_tts_provider(_org("", False))
    assert sel["provider"] == "browser"
    assert sel["reason"] == "no_elevenlabs_key"


def _install_fake_elevenlabs(should_raise=False):
    mod = types.ModuleType("elevenlabs")

    class VoiceSettings:
        def __init__(self, **kw):
            self.kw = kw

    class _TTS:
        def convert(self, **kwargs):
            if should_raise:
                raise RuntimeError("401 unauthorized")
            assert kwargs["voice_id"], "voice_id must be applied"
            return [b"AUDIO", b"DATA"]

    class ElevenLabs:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.text_to_speech = _TTS()

    mod.ElevenLabs = ElevenLabs
    mod.VoiceSettings = VoiceSettings
    sys.modules["elevenlabs"] = mod


def test_generate_tts_uses_elevenlabs_when_configured():
    _install_fake_elevenlabs(should_raise=False)
    org = _org("sk_real", True)
    res = asyncio.run(integrations.generate_tts(org, "alice", "Hello there"))
    assert res["provider"] == "elevenlabs", "must use ElevenLabs when configured"
    assert res["audio_url"] and res["audio_url"].startswith("data:audio/mpeg;base64,")
    assert res["error"] is None


def test_generate_tts_no_silent_fallback_on_error():
    """If ElevenLabs is configured but the API call fails, we must NOT silently fall back
    to the browser voice — we surface 'elevenlabs_error' so regressions are visible."""
    _install_fake_elevenlabs(should_raise=True)
    org = _org("sk_real", True)
    res = asyncio.run(integrations.generate_tts(org, "alice", "Hello there"))
    assert res["provider"] == "elevenlabs_error"
    assert res["provider"] != "browser"
    assert res["error"] is not None


def test_generate_tts_browser_when_disabled(monkeypatch):
    monkeypatch.setattr(os, "environ", {**os.environ, "ELEVENLABS_API_KEY": ""})
    org = _org("", False)
    res = asyncio.run(integrations.generate_tts(org, "alice", "Hello"))
    assert res["provider"] == "browser"
    assert res["audio_url"] is None
