import os
import base64
import logging
from pathlib import Path
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger(__name__)
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# UK-focused AI voice catalog (ElevenLabs voice IDs where available)
VOICE_CATALOG = [
    {"id": "george",  "name": "George",   "gender": "male",   "accent": "British",  "description": "Warm, mature UK male — trustworthy and calm.", "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb"},
    {"id": "charlie", "name": "Charlie",  "gender": "male",   "accent": "British",  "description": "Confident young UK male — energetic closer.",   "elevenlabs_voice_id": "IKne3meq5aSn9XLyUdCD"},
    {"id": "daniel",  "name": "Daniel",   "gender": "male",   "accent": "British",  "description": "Authoritative UK male — corporate and clear.",  "elevenlabs_voice_id": "onwK4e9ZLuTAKqWW03F9"},
    {"id": "alice",   "name": "Alice",    "gender": "female", "accent": "British",  "description": "Professional UK female — clear and friendly.",  "elevenlabs_voice_id": "Xb7hH8MSUJpSbSDYk0k2"},
    {"id": "lily",    "name": "Lily",     "gender": "female", "accent": "British",  "description": "Soft, approachable UK female — great rapport.", "elevenlabs_voice_id": "pFZP5JQG7iQjIQuC4Bku"},
    {"id": "matilda", "name": "Matilda",  "gender": "female", "accent": "American", "description": "Bright US female — upbeat and persuasive.",    "elevenlabs_voice_id": "XrExE9yKIg1WjnnlVkGX"},
]


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


def _chat(session_id: str, system_message: str, model: str = "claude-sonnet-4-6") -> LlmChat:
    return LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system_message,
    ).with_model("anthropic", model)


async def llm_generate(session_id: str, system_message: str, prompt: str, model: str = "claude-sonnet-4-6") -> str:
    chat = _chat(session_id, system_message, model)
    resp = await chat.send_message(UserMessage(text=prompt))
    return resp if isinstance(resp, str) else str(resp)


async def generate_script(product: str, audience: str, objective: str, tone: str, session_id: str) -> str:
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
    return await llm_generate(session_id, system, prompt)


async def agent_reply(script: str, history: list, prospect_message: str, session_id: str) -> str:
    system = (
        "You are an AI outbound sales agent on a live UK cold call. You strictly follow the "
        "provided SCRIPT but adapt naturally to what the prospect says. You handle objections "
        "professionally. If the prospect asks to be removed, says 'not interested', 'stop calling', "
        "'opt out', or 'do not call', you MUST immediately, politely confirm you will remove them and "
        "end the call. Keep responses short and human, like real speech. Output ONLY the agent's spoken words."
        f"\n\nSCRIPT:\n{script}"
    )
    convo = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history])
    prompt = f"Conversation so far:\n{convo}\n\nPROSPECT: {prospect_message}\n\nAGENT:"
    return await llm_generate(session_id, system, prompt)


async def analyze_transcript(transcript: str, session_id: str) -> dict:
    import json
    system = (
        "You are a call QA analyst. Analyse the cold call transcript and respond with STRICT JSON only, "
        'no markdown, with keys: "sentiment" (one of "positive","neutral","negative"), '
        '"opted_out" (boolean — true if prospect asked to stop/opt-out/do-not-call), '
        '"summary" (one sentence), "next_action" (short suggestion), "score" (0-100 interest score).'
    )
    prompt = f"Transcript:\n{transcript}\n\nReturn the JSON analysis."
    raw = await llm_generate(session_id, system, prompt)
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


async def generate_tts(org: dict, voice_id: str, text: str) -> dict:
    """Generate speech using the selected provider. Logs selection; never falls back silently
    when a valid ElevenLabs key exists. Returns {provider, voice, audio_url, reason, error}."""
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
        settings = VoiceSettings(
            stability=float(integ.get("elevenlabs_stability", 0.5)),
            similarity_boost=float(integ.get("elevenlabs_similarity", 0.75)),
            style=float(integ.get("elevenlabs_style", 0.0)),
            use_speaker_boost=True,
        )
        model_id = integ.get("elevenlabs_model", "eleven_multilingual_v2")
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
        return {"provider": "elevenlabs_error", "voice": voice, "audio_url": None,
                "reason": "elevenlabs_call_failed", "error": str(e)[:200]}


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
        chat = _chat(session_id, system)
        from emergentintegrations.llm.chat import UserMessage
        resp = await chat.send_message(UserMessage(text=prompt))
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
