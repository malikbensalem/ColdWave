"""Unit tests for audit diff/masking and KB opening guardrails."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audit  # noqa: E402
import integrations  # noqa: E402


def test_diff_detects_changed_fields():
    d = audit._diff({"status": "new", "name": "A"}, {"status": "positive", "name": "A"})
    assert d == {"status": {"before": "new", "after": "positive"}}


def test_diff_handles_create_and_delete():
    assert "name" in audit._diff(None, {"name": "X"})
    assert "name" in audit._diff({"name": "X"}, None)


def test_mask_redacts_secrets():
    masked = audit._mask({"elevenlabs_api_key": "sk_secret", "name": "ok"})
    assert masked["elevenlabs_api_key"] == "***redacted***"
    assert masked["name"] == "ok"


def test_guardrails_block_profanity():
    ok, reason = integrations.passes_guardrails("Hi, this is a damn good offer")
    assert ok is False
    assert reason.startswith("profanity")


def test_guardrails_allow_clean_text():
    ok, reason = integrations.passes_guardrails("Hello, I help UK teams book more meetings.")
    assert ok is True
    assert reason == "ok"
