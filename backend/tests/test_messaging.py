"""Unit tests for messaging (WhatsApp) provider abstraction, PII redaction, and rate-limit config."""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import messaging  # noqa: E402


def test_mask_phone_redacts_pii():
    assert messaging.mask_phone("+447700900123") == "+447***23"
    assert messaging.mask_phone("12345") == "***"
    assert messaging.mask_phone("") == ""


def test_mock_provider_returns_message_id():
    prov = messaging.MockWhatsAppProvider()
    res = asyncio.run(prov.send_text("+447700900123", "hi"))
    assert res["mock"] is True
    assert res["messages"][0]["id"].startswith("mock_wamid_")


def test_get_provider_falls_back_to_mock_without_creds(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "")
    org = {"integrations": {}}
    prov, is_mock = messaging.get_whatsapp_provider(org)
    assert is_mock is True
    assert isinstance(prov, messaging.MockWhatsAppProvider)


def test_get_provider_uses_cloud_when_configured():
    org = {"integrations": {"whatsapp_phone_number_id": "123", "whatsapp_access_token": "tok"}}
    prov, is_mock = messaging.get_whatsapp_provider(org)
    assert is_mock is False
    assert isinstance(prov, messaging.WhatsAppCloudProvider)
    assert prov.url.endswith("/123/messages")
