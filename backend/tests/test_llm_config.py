"""Unit tests for bring-your-own LLM key config resolution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import integrations  # noqa: E402


def test_uses_custom_key_when_present():
    org = {"integrations": {"llm_provider": "openai", "llm_model": "gpt-4o", "openai_api_key": "sk-mine"}}
    cfg = integrations.llm_config(org)
    assert cfg["provider"] == "openai"
    assert cfg["model"] == "gpt-4o"
    assert cfg["api_key"] == "sk-mine"
    assert cfg["source"] == "custom"


def test_falls_back_to_emergent_without_custom_key():
    org = {"integrations": {"llm_provider": "anthropic", "llm_model": "claude-sonnet-4-6"}}
    cfg = integrations.llm_config(org)
    assert cfg["source"] == "emergent"
    assert cfg["provider"] == "anthropic"


def test_invalid_model_falls_back_to_default():
    org = {"integrations": {"llm_provider": "gemini", "llm_model": "not-a-real-model"}}
    cfg = integrations.llm_config(org)
    assert cfg["model"] in integrations.LLM_MODELS["gemini"]


def test_model_lists_present_for_all_providers():
    for p in ("openai", "anthropic", "gemini"):
        assert len(integrations.LLM_MODELS[p]) > 0
