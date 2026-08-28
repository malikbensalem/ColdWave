"""Tests for the Telnyx TeXML ConversationRelay path (built-in STT/TTS/turn-taking).

Pure/offline: TeXML markup generation + voice-string selection. No network calls.
"""
import os
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

import telnyx_texml as TT


def _parse(xml: str):
    root = ET.fromstring(xml)
    cr = root.find("./Connect/ConversationRelay")
    assert cr is not None, "ConversationRelay noun missing"
    return root, cr


def test_texml_native_voice_default():
    org = {"id": "o1", "integrations": {"telnyx_tts_provider": "telnyx"}}
    xml = TT._relay_texml("call1", "Hello there", None, org)
    root, cr = _parse(xml)
    assert cr.attrib["voice"] == "Telnyx.Natural.abbie"
    assert cr.attrib["welcomeGreeting"] == "Hello there"
    assert cr.attrib["url"].startswith("wss://") or cr.attrib["url"].startswith("ws://")
    assert cr.attrib["url"].endswith("/api/telephony/telnyx/relay/ws/call1")
    assert cr.attrib["transcriptionProvider"] == "deepgram"
    # Connect action hangs up when ConversationRelay ends
    assert root.find("./Connect").attrib["action"].endswith("/texml/ended/call1")


def test_texml_native_voice_custom():
    org = {"id": "o2", "integrations": {"telnyx_tts_provider": "telnyx", "telnyx_native_voice": "Telnyx.NaturalHD.astra"}}
    _, cr = _parse(TT._relay_texml("c", "hi", None, org))
    assert cr.attrib["voice"] == "Telnyx.NaturalHD.astra"


def test_texml_elevenlabs_voice_string():
    # ElevenLabs provider -> voice string ElevenLabs.<model>.<voiceId> using the campaign voice.
    org = {"id": "o3", "voice_characteristics": {}, "integrations": {
        "telnyx_tts_provider": "elevenlabs", "elevenlabs_model": "eleven_flash_v2_5"}}
    # 'george' resolves to a catalog voice with an elevenlabs_voice_id
    _, cr = _parse(TT._relay_texml("c", "hi", "george", org))
    v = cr.attrib["voice"]
    assert v.startswith("ElevenLabs.eleven_flash_v2_5."), v


def test_texml_elevenlabs_falls_back_to_native_without_voice():
    org = {"id": "o4", "integrations": {"telnyx_tts_provider": "elevenlabs"}}
    _, cr = _parse(TT._relay_texml("c", "hi", None, org))
    assert cr.attrib["voice"] == "Telnyx.Natural.abbie"


def test_relay_voice_helper_direct():
    assert TT._relay_voice({"integrations": {"telnyx_tts_provider": "telnyx"}}, None) == "Telnyx.Natural.abbie"


def test_texml_escapes_greeting():
    org = {"id": "o5", "integrations": {}}
    xml = TT._relay_texml("c", 'Hi "Bob" & friends <ok>', None, org)
    # Must remain well-formed XML after escaping
    _, cr = _parse(xml)
    assert "Bob" in cr.attrib["welcomeGreeting"]
