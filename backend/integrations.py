import os
import base64
import logging
from pathlib import Path
from dotenv import load_dotenv

# emergentintegrations is only available via Emergent's private index. Make it optional so the
# app runs locally (where the user supplies their own provider key in Settings → AI); we fall
# back to calling the provider directly via litellm.
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    _HAS_EMERGENT = True
except Exception:  # pragma: no cover
    LlmChat = None
    UserMessage = None
    _HAS_EMERGENT = False

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger(__name__)
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# UK-focused AI voice catalog (ElevenLabs voice IDs where available)
VOICE_CATALOG = [
    {"id": "george",  "name": "George",   "gender": "male",   "accent": "British",  "description": "Warm, mature UK male — trustworthy and calm.", "persona": "A warm, seasoned account executive who builds trust through calm, measured conversation.", "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb"},
    {"id": "charlie", "name": "Charlie",  "gender": "male",   "accent": "British",  "description": "Confident young UK male — energetic closer.",   "persona": "An energetic young sales rep who is upbeat, confident and great at moving the conversation to a close.", "elevenlabs_voice_id": "IKne3meq5aSn9XLyUdCD"},
    {"id": "daniel",  "name": "Daniel",   "gender": "male",   "accent": "British",  "description": "Authoritative UK male — corporate and clear.",  "persona": "A polished, authoritative business development manager who speaks clearly and professionally.", "elevenlabs_voice_id": "onwK4e9ZLuTAKqWW03F9"},
    {"id": "alice",   "name": "Alice",    "gender": "female", "accent": "British",  "description": "Professional UK female — clear and friendly.",  "persona": "A friendly, professional sales consultant who is clear, approachable and helpful.", "elevenlabs_voice_id": "Xb7hH8MSUJpSbSDYk0k2"},
    {"id": "lily",    "name": "Lily",     "gender": "female", "accent": "British",  "description": "Soft, approachable UK female — great rapport.", "persona": "A soft-spoken, empathetic representative who quickly builds rapport and puts people at ease.", "elevenlabs_voice_id": "pFZP5JQG7iQjIQuC4Bku"},
    {"id": "matilda", "name": "Matilda",  "gender": "female", "accent": "American", "description": "Bright US female — upbeat and persuasive.",    "persona": "A bright, persuasive US-based account manager who is upbeat and enthusiastic.", "elevenlabs_voice_id": "XrExE9yKIg1WjnnlVkGX"},
]

# Selectable ElevenLabs models (dropdown in Settings).
ELEVENLABS_MODELS = [
    "eleven_multilingual_v2",
    "eleven_turbo_v2_5",
    "eleven_turbo_v2",
    "eleven_flash_v2_5",
    "eleven_monolingual_v1",
]


def get_elevenlabs_models():
    return ELEVENLABS_MODELS


def get_voice(voice_id: str):
    return next((v for v in VOICE_CATALOG if v["id"] == voice_id), None)


def _eleven_key(org_key: str = "") -> str:
    return org_key or os.environ.get("ELEVENLABS_API_KEY", "")


async def generate_voice_preview(voice_id: str, text: str, org_key: str = "") -> dict:
    """Returns {mock: bool, audio_url: str|None, voice: dict}."""
    voice = get_voice(voice_id)
    if not voice:
        return {"mock": True, "audio_url": None, "voice": None, "error": "voice not found"}
    key = _eleven_key(org_key)
    if not key:
        return {"mock": True, "audio_url": None, "voice": voice}
    try:
        from elevenlabs import ElevenLabs, VoiceSettings
        client = ElevenLabs(api_key=key)
        audio = client.text_to_speech.convert(
            text=text[:500],
            voice_id=voice["elevenlabs_voice_id"],
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
        )
        data = b""
        for chunk in audio:
            data += chunk
        b64 = base64.b64encode(data).decode()
        return {"mock": False, "audio_url": f"data:audio/mpeg;base64,{b64}", "voice": voice}
    except Exception as e:
        logger.error(f"ElevenLabs error: {e}")
        return {"mock": True, "audio_url": None, "voice": voice, "error": str(e)}


# ---------------- LLM provider config (bring-your-own keys + Emergent fallback) ----------------
LLM_MODELS = {
    "openai": ["gpt-5.4", "gpt-5.5", "gpt-5.4-mini", "gpt-5.2", "gpt-5.1", "gpt-5", "gpt-5-mini",
               "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-8", "claude-opus-4-7", "claude-haiku-4-5-20251001",
                  "claude-sonnet-4-5-20250929"],
    "gemini": ["gemini-2.5-flash-lite", "gemini-3.5-flash", "gemini-3-flash-preview",
               "gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
}
PROVIDER_KEY_FIELD = {"openai": "openai_api_key", "anthropic": "anthropic_api_key", "gemini": "gemini_api_key"}
DEFAULT_MODEL = {"openai": "gpt-5.4", "anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.5-flash-lite"}


def get_llm_models():
    return LLM_MODELS


def llm_config(org: dict) -> dict:
    """Resolve provider/model/api_key. Uses the workspace's own provider key when present,
    otherwise the Emergent Universal key. Returns {provider, model, api_key, source}."""
    integ = (org or {}).get("integrations", {})
    provider = integ.get("llm_provider") or "anthropic"
    if provider not in LLM_MODELS:
        provider = "anthropic"
    model = integ.get("llm_model") or DEFAULT_MODEL[provider]
    if model not in LLM_MODELS[provider]:
        model = DEFAULT_MODEL[provider]
    custom_key = integ.get(PROVIDER_KEY_FIELD[provider], "")
    try:
        temperature = float(integ.get("llm_temperature", 0.6))
    except (TypeError, ValueError):
        temperature = 0.6
    try:
        max_sentences = int(integ.get("llm_max_sentences", 2))
    except (TypeError, ValueError):
        max_sentences = 2
    chunking = integ.get("llm_chunking", True)
    common = {"provider": provider, "model": model, "temperature": temperature,
              "max_sentences": max_sentences, "chunking": chunking}
    if custom_key:
        return {**common, "api_key": custom_key, "source": "custom"}
    return {**common, "api_key": EMERGENT_LLM_KEY, "source": "emergent"}


async def validate_llm_key(provider: str, api_key: str, model: str = "") -> dict:
    """Validate a provider key via a tiny chat round-trip."""
    if provider not in LLM_MODELS:
        return {"valid": False, "message": f"Unknown provider '{provider}'."}
    if not api_key:
        return {"valid": False, "message": "No API key provided."}
    use_model = model if model in LLM_MODELS[provider] else DEFAULT_MODEL[provider]
    try:
        if _HAS_EMERGENT:
            chat = LlmChat(api_key=api_key, session_id="keycheck", system_message="Reply with 'ok'.").with_model(provider, use_model)
            await chat.send_message(UserMessage(text="ping"))
        else:
            import litellm
            mdl = f"{_LITELLM_PREFIX.get(provider, '')}{use_model}"
            await litellm.acompletion(model=mdl, api_key=api_key,
                                      messages=[{"role": "user", "content": "ping"}], max_tokens=5)
        return {"valid": True, "message": f"{provider} key works with {use_model}."}
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "ratelimit" in low or "quota" in low or "billing" in low or "429" in low:
            return {"valid": False, "message": f"{provider} key authenticated, but quota/billing is exceeded — add credits at the provider."}
        if "401" in msg or "auth" in low or "api key" in low or "api_key" in low:
            return {"valid": False, "message": f"Invalid {provider} API key."}
        return {"valid": False, "message": f"Validation failed: {msg[:160]}"}


def _chat(session_id: str, system_message: str, org: dict = None) -> "LlmChat":
    cfg = llm_config(org or {})
    prefix = (org or {}).get("_system_prefix", "")
    sys_msg = f"{prefix}\n\n{system_message}" if prefix else system_message
    return LlmChat(
        api_key=cfg["api_key"],
        session_id=session_id,
        system_message=sys_msg,
    ).with_model(cfg["provider"], cfg["model"])


# litellm model prefixes for the local/direct fallback path.
_LITELLM_PREFIX = {"openai": "", "anthropic": "anthropic/", "gemini": "gemini/"}


async def _direct_llm_generate(cfg: dict, system_message: str, prompt: str, prefix: str = "") -> str:
    """Provider-direct call (used when emergentintegrations is unavailable, e.g. local dev).
    Requires a workspace-supplied provider key (cfg['source'] == 'custom')."""
    import litellm
    sys_msg = f"{prefix}\n\n{system_message}" if prefix else system_message
    model = f"{_LITELLM_PREFIX.get(cfg['provider'], '')}{cfg['model']}"
    resp = await litellm.acompletion(
        model=model, api_key=cfg["api_key"],
        messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
    )
    return (resp["choices"][0]["message"]["content"] or "") if resp else ""


async def llm_generate(session_id: str, system_message: str, prompt: str, org: dict = None) -> str:
    cfg = llm_config(org or {})
    prefix = (org or {}).get("_system_prefix", "")
    if _HAS_EMERGENT:
        chat = _chat(session_id, system_message, org)
        resp = await chat.send_message(UserMessage(text=prompt))
        return resp if isinstance(resp, str) else str(resp)
    # Local/direct fallback: needs the workspace's own provider key.
    if cfg["source"] != "custom" or not cfg["api_key"]:
        raise RuntimeError(
            "AI is unavailable: the Emergent key requires the emergentintegrations package (Emergent-hosted). "
            "To run locally, add your own OpenAI/Anthropic/Gemini API key in Settings → Integrations → AI Language Model."
        )
    return await _direct_llm_generate(cfg, system_message, prompt, prefix)


async def generate_script(product: str, audience: str, objective: str, tone: str, session_id: str,
                          script_type: str = "line_by_line", personality: str = "", org: dict = None) -> str:
    if script_type == "personality":
        system = (
            "You design AI sales-agent PERSONAS for UK B2B cold calls. Produce a concise persona brief the "
            "agent will embody to hold a natural, unscripted conversation. Stay compliant (clear opt-out, no "
            "misleading claims). Output labelled sections only."
        )
        prompt = (
            f"Create a sales-agent persona.\nProduct/Service: {product}\nTarget audience: {audience}\n"
            f"Objective: {objective}\nDesired tone/personality: {personality or tone}\n\n"
            "Sections: [PERSONA NAME & ROLE], [PERSONALITY & TONE], [CONVERSATION GOALS], "
            "[OBJECTION STYLE], [OPT-OUT / COMPLIANCE]. Keep it tight."
        )
        return await llm_generate(session_id, system, prompt, org)

    system = (
        "You are an expert UK B2B cold-calling copywriter. You write compliant, natural "
        "telephone scripts for outbound sales. You ALWAYS open by stating the caller's name "
        "and company, you ALWAYS offer an easy opt-out ('If now's not a good time, I'm happy to "
        "remove you from our list'), and you never use misleading claims. Keep it concise and "
        "conversational, formatted with clear stage labels."
    )
    prompt = (
        f"Write a cold call script.\n"
        f"Product/Service: {product}\n"
        f"Target audience: {audience}\n"
        f"Objective of the call: {objective}\n"
        f"Tone: {tone}\n\n"
        "Structure it with these labelled sections: [OPENING], [HOOK], [QUALIFYING QUESTIONS], "
        "[VALUE PROPOSITION], [OBJECTION HANDLING] (cover 3 common objections), [CLOSE], "
        "[OPT-OUT / COMPLIANCE]. Keep total length suitable for a 2-3 minute call."
    )
    return await llm_generate(session_id, system, prompt, org)


def _company_block(company_overview: str) -> str:
    if not company_overview:
        return ""
    return ("\n\nCOMPANY OVERVIEW (authoritative facts about your company — use these to answer ANY "
            f"question, including ones not covered by the script):\n{company_overview[:4000]}")


def _agent_system_and_prompt(script, history, prospect_message, script_type, personality, company_overview, brief=False, max_sentences=2):
    compliance = (
        "If the prospect asks to be removed, says 'not interested', 'stop calling', 'opt out', or "
        "'do not call', you MUST immediately, politely confirm you will remove them and end the call. "
        "Never use misleading claims. Keep responses short and human, like real speech. "
        "Output ONLY the agent's spoken words."
    )
    if brief:
        n = max(1, int(max_sentences or 2))
        compliance += (f" This is a LIVE PHONE CALL — reply in at most {n} short, natural sentence(s). "
                       "Never monologue; make a single point or ask a question, then stop.")
    if script_type == "personality":
        system = (
            "You are an AI outbound sales agent on a live UK cold call. You EMBODY the persona below and "
            "hold a natural, unscripted conversation, steering toward the goal. "
            f"{compliance}\n\nPERSONA:\n{personality or script}"
            + _company_block(company_overview)
        )
    else:
        system = (
            "You are an AI outbound sales agent on a live UK cold call. You follow the provided SCRIPT "
            "line by line, but adapt naturally. If the prospect asks something the script does NOT cover, "
            "answer it accurately using the COMPANY OVERVIEW (never invent facts). "
            "IMPORTANT — the script contains stage labels in square brackets like [OPENING], [HOOK], "
            "[CLOSE], and sometimes speaker/role labels or the respondent's placeholder name. NEVER read "
            "these out loud. Speak ONLY the natural spoken words a real person would say; skip any "
            "bracketed labels, section titles, or placeholder names entirely. "
            f"{compliance}\n\nSCRIPT:\n{script}"
            + _company_block(company_overview)
        )
    convo = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history])
    prompt = f"Conversation so far:\n{convo}\n\nPROSPECT: {prospect_message}\n\nAGENT:"
    return system, prompt


async def agent_reply(script: str, history: list, prospect_message: str, session_id: str,
                      script_type: str = "line_by_line", personality: str = "",
                      company_overview: str = "", org: dict = None) -> str:
    system, prompt = _agent_system_and_prompt(script, history, prospect_message, script_type, personality, company_overview)
    return await llm_generate(session_id, system, prompt, org)


async def stream_agent_reply(script: str, history: list, prospect_message: str, session_id: str,
                             script_type: str = "line_by_line", personality: str = "",
                             company_overview: str = "", org: dict = None, brief: bool = False):
    """Async generator yielding partial reply text as the LLM produces it (for live voice streaming).
    Falls back to a single full-reply yield if streaming is unavailable."""
    cfg = llm_config(org or {})
    system, prompt = _agent_system_and_prompt(script, history, prospect_message, script_type, personality,
                                              company_overview, brief=brief, max_sentences=cfg.get("max_sentences", 2))
    prefix = (org or {}).get("_system_prefix", "")
    sys_msg = f"{prefix}\n\n{system}" if prefix else system
    if _HAS_EMERGENT:
        try:
            from emergentintegrations.llm.chat import TextDelta
            chat = LlmChat(api_key=cfg["api_key"], session_id=session_id, system_message=sys_msg).with_model(cfg["provider"], cfg["model"])
            try:
                chat = chat.with_params(temperature=cfg.get("temperature", 0.6))
            except Exception:
                pass
            async for ev in chat.stream_message(UserMessage(text=prompt)):
                if isinstance(ev, TextDelta) and ev.content:
                    yield ev.content
            return
        except Exception as e:
            logger.error(f"stream_agent_reply streaming failed, falling back: {e}")
    # Fallback: non-streaming full reply in one chunk.
    full = await llm_generate(session_id, system, prompt, org)
    if full:
        yield full


async def generate_opening_line(org: dict, script_content: str, personality: str, script_type: str,
                                company_overview: str, agent_name: str, session_id: str) -> str:
    """Generate a natural opening line for a cold call from the persona/blueprint (not a hardcoded string).
    Used when the script is personality-driven or has no usable scripted first line."""
    persona_block = personality or script_content or "A friendly, professional outbound sales agent."
    system = (
        "You are an AI outbound sales agent about to open a live UK cold call. "
        f"Your name is {agent_name}. Speak the FIRST line only — a short, natural, warm opener that introduces "
        "yourself/your company and politely asks for a moment. Never read stage labels, titles or placeholders. "
        "Output ONLY the spoken words (no quotes, no preamble).\n\n"
        f"YOUR PERSONA / APPROACH:\n{persona_block}"
        + (_company_block(company_overview) if company_overview else "")
    )
    try:
        reply = await llm_generate(session_id, system, "Give me the opening line now.", org)
        return (reply if isinstance(reply, str) else str(reply)).strip().strip('"')
    except Exception as e:
        logger.error(f"opening-line generation failed: {e}")
        return ""


async def analyze_transcript(transcript: str, session_id: str, org: dict = None) -> dict:
    import json
    system = (
        "You are a call QA analyst. Analyse the cold call transcript and respond with STRICT JSON only, "
        'no markdown, with keys: "sentiment" (one of "positive","neutral","negative"), '
        '"opted_out" (boolean — true if prospect asked to stop/opt-out/do-not-call), '
        '"summary" (one sentence), "next_action" (short suggestion), "score" (0-100 interest score).'
    )
    prompt = f"Transcript:\n{transcript}\n\nReturn the JSON analysis."
    raw = await llm_generate(session_id, system, prompt, org)
    try:
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        low = raw.lower()
        return {
            "sentiment": "positive" if "positive" in low else ("negative" if "negative" in low else "neutral"),
            "opted_out": "opt" in low or "do not call" in low or "do-not-call" in low,
            "summary": raw[:200],
            "next_action": "Review transcript manually.",
            "score": 50,
        }


# ---------------- ElevenLabs: deterministic TTS selection + validation ----------------
def select_tts_provider(org: dict) -> dict:
    """Deterministic provider selection. Returns {provider, reason, key_present}.
    Rules: if org/env ElevenLabs key present AND elevenlabs_enabled -> 'elevenlabs';
    else 'browser' with explicit reason. No silent fallback."""
    integ = (org or {}).get("integrations", {})
    key = integ.get("elevenlabs_api_key") or os.environ.get("ELEVENLABS_API_KEY", "")
    enabled = integ.get("elevenlabs_enabled", False)
    if key and enabled:
        return {"provider": "elevenlabs", "reason": "valid_config", "key_present": True}
    if key and not enabled:
        return {"provider": "browser", "reason": "elevenlabs_key_present_but_disabled", "key_present": True}
    return {"provider": "browser", "reason": "no_elevenlabs_key", "key_present": False}


def validate_elevenlabs_key(api_key: str) -> dict:
    """Ping ElevenLabs to confirm the key is valid. Returns {valid, message, voice_count}."""
    if not api_key:
        return {"valid": False, "message": "No API key provided."}
    try:
        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=api_key)
        voices = client.voices.get_all()
        count = len(getattr(voices, "voices", []) or [])
        return {"valid": True, "message": f"Key is valid. {count} voices available on this account.", "voice_count": count}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "unauthorized" in msg.lower():
            return {"valid": False, "message": "Invalid API key (unauthorized)."}
        return {"valid": False, "message": f"Validation failed: {msg[:160]}"}


def _dynamic_voice_params(text: str) -> tuple:
    """Heuristic dynamic delivery: adapt (stability, style, speed) to the utterance context.
    Questions/excitement → more expressive & a touch faster; long/factual → steadier & calmer."""
    t = (text or "").strip()
    lower = t.lower()
    excited = ("!" in t) or any(w in lower for w in ("great", "amazing", "fantastic", "love", "excited", "brilliant", "perfect"))
    question = t.endswith("?") or lower.startswith(("do ", "would ", "are ", "can ", "how ", "what ", "when ", "is ", "could "))
    longish = len(t) > 220
    if excited:
        return (0.30, 0.55, 1.08)
    if question:
        return (0.40, 0.40, 1.05)
    if longish:
        return (0.65, 0.15, 0.97)
    return (0.50, 0.30, 1.0)


async def generate_tts(org: dict, voice_id: str, text: str, model: str = None) -> dict:
    """Generate speech using the selected provider. Logs selection; never falls back silently
    when a valid ElevenLabs key exists. Returns {provider, voice, audio_url, reason, error}.
    Pass `model` to override the org's ElevenLabs model (e.g. a fast real-time model for live calls)."""
    selection = select_tts_provider(org)
    voice = get_voice(voice_id)
    integ = (org or {}).get("integrations", {})
    key = integ.get("elevenlabs_api_key") or os.environ.get("ELEVENLABS_API_KEY", "")

    if selection["provider"] != "elevenlabs":
        logger.info(f"TTS selection -> browser (reason={selection['reason']}) voice={voice_id}")
        return {"provider": "browser", "voice": voice, "audio_url": None,
                "reason": selection["reason"], "error": None}

    if not voice:
        return {"provider": "browser", "voice": None, "audio_url": None,
                "reason": "voice_not_found", "error": "voice_not_found"}

    try:
        from elevenlabs import ElevenLabs, VoiceSettings
        client = ElevenLabs(api_key=key)
        vc = (org or {}).get("voice_characteristics", {}).get(voice_id, {})

        # Base values: per-voice override → org integration setting → default.
        stability = vc.get("stability", integ.get("elevenlabs_stability", 0.5))
        style = vc.get("style", integ.get("elevenlabs_style", 0.0))
        similarity = integ.get("elevenlabs_similarity", 0.75)
        speed = vc.get("speed", integ.get("elevenlabs_speed", 1.0))

        # Dynamic delivery: vary stability/style/speed by the utterance's context.
        if vc.get("dynamic"):
            stability, style, speed = _dynamic_voice_params(text)

        vs_kwargs = dict(
            stability=float(max(0.0, min(1.0, float(stability)))),
            similarity_boost=float(max(0.0, min(1.0, float(similarity)))),
            style=float(max(0.0, min(1.0, float(style)))),
            use_speaker_boost=True,
        )
        try:
            vs_kwargs["speed"] = float(max(0.7, min(1.2, float(speed))))
        except (TypeError, ValueError):
            pass
        try:
            settings = VoiceSettings(**vs_kwargs)
        except TypeError:
            vs_kwargs.pop("speed", None)  # older SDK without speed support
            settings = VoiceSettings(**vs_kwargs)

        model_id = model or integ.get("elevenlabs_model", "eleven_multilingual_v2")
        audio = client.text_to_speech.convert(
            text=text[:600], voice_id=voice["elevenlabs_voice_id"],
            model_id=model_id, voice_settings=settings)
        data = b""

        for chunk in audio:
            data += chunk
        b64 = base64.b64encode(data).decode()

        logger.info(f"TTS selection -> elevenlabs OK voice={voice['name']} model={model_id} bytes={len(data)}")
        return {"provider": "elevenlabs", "voice": voice,
                "audio_url": f"data:audio/mpeg;base64,{b64}", "reason": "valid_config", "error": None}
    except Exception as e:
        # IMPORTANT: do NOT silently fall back when a key was configured. Surface the error.
        logger.error(f"TTS elevenlabs ERROR (configured key present) voice={voice_id}: {e}")
        return {"provider": "elevenlabs_error1", "voice": voice, "audio_url": None,
                "reason": "elevenlabs_call_failed", "error": str(e)}


# ---------------- Knowledge-base guided opening line + guardrails ----------------
PROFANITY = {"damn", "hell", "shit", "fuck", "bastard", "crap", "bloody", "arse"}


def passes_guardrails(text: str) -> tuple:
    low = text.lower()
    for w in PROFANITY:
        if w in low.split() or f" {w} " in f" {low} ":
            return False, f"profanity:{w}"
    return True, "ok"


async def generate_kb_opening(org: dict, kb_entries: list, product_context: str,
                              creativity: str, max_length: int, session_id: str) -> dict:
    """KB-guided opening with guardrails + compliance + fallback signalling.
    Returns {opening, sources, fallback, reason}."""
    if not kb_entries:
        return {"opening": None, "sources": [], "fallback": True, "reason": "kb_empty"}

    temp_map = {"low": 0.2, "medium": 0.6, "high": 0.9}
    kb_text = "\n\n".join([f"[{e['title']}] {e['content'][:600]}" for e in kb_entries[:5]])
    sources = [e["title"] for e in kb_entries[:5]]
    creativity_word = {"low": "conservative and close to the facts",
                       "medium": "natural and lightly varied",
                       "high": "creative and engaging"}.get(creativity, "natural")
    system = (
        "You are a UK B2B cold-call opener writer. Using ONLY the knowledge base provided, craft ONE "
        "natural spoken opening line for a cold call. Constraints: on-brand, professional, "
        "compliance-safe (no misleading claims, no pressure), no profanity, and ALWAYS sound human. "
        f"Style: {creativity_word}. Keep it under {max_length} characters. Output ONLY the opening line."
    )
    prompt = f"Knowledge base:\n{kb_text}\n\nProduct/context: {product_context}\n\nWrite the opening line:"
    try:
        resp = await llm_generate(session_id, system, prompt, org)
        opening = (resp if isinstance(resp, str) else str(resp)).strip().strip('"')
        if len(opening) > max_length:
            opening = opening[:max_length].rsplit(" ", 1)[0] + "…"
        ok, reason = passes_guardrails(opening)
        if not ok:
            logger.warning(f"KB opening failed guardrails ({reason}); falling back to scripted.")
            return {"opening": None, "sources": sources, "fallback": True, "reason": reason}
        logger.info(f"KB opening generated (sources={sources}) len={len(opening)}")
        return {"opening": opening, "sources": sources, "fallback": False, "reason": "kb_generated"}
    except Exception as e:
        logger.error(f"KB opening generation failed: {e}")
        return {"opening": None, "sources": sources, "fallback": True, "reason": f"llm_error:{str(e)[:80]}"}
