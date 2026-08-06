"""Twilio Programmable Voice <Gather> webhooks — turn-based AI cold call (fallback path).

This is the non-streaming fallback used when Twilio voice mode is 'gather'. The preferred,
sub-1s path is ConversationRelay (conversation_relay.py). This path is optimised for low
latency and natural, interruptible turn-taking:
  - the AI prompt is nested INSIDE <Gather> so the prospect can barge in / talk over the AI,
  - TTS uses the fast `eleven_flash_v2_5` model,
  - synthesised audio is stored in MongoDB (not in-process memory) so it is reliably served
    back to Twilio even on multi-worker / horizontally-scaled deployments.
No auth on these routes — Twilio calls them; they are keyed by the (unguessable) call id.
"""
import os
import base64
import hmac
import hashlib
import logging
import time as _time
from uuid import uuid4
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from bson.binary import Binary
from database import db
from integrations import generate_tts, agent_reply, analyze_transcript

logger = logging.getLogger("twilio_voice")


def _now():
    return datetime.now(timezone.utc).isoformat()


def public_base_url() -> str:
    u = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("REACT_APP_BACKEND_URL")
    if not u:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL"):
                        u = line.strip().split("=", 1)[1]
                        break
        except Exception:
            u = ""
    return (u or "").strip().rstrip("/")


def twilio_signature_enabled() -> bool:
    return os.environ.get("TWILIO_VALIDATE_SIGNATURE", "true").lower() in ("1", "true", "yes", "on")


def _compute_twilio_sig(auth_token: str, url: str, params: dict) -> str:
    s = url
    for k in sorted(params.keys()):
        s += k + str(params[k])
    mac = hmac.new(auth_token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode()


async def twilio_auth_token_for_org(org_id: str) -> str:
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0, "integrations": 1})
    return ((org or {}).get("integrations", {}) or {}).get("twilio_auth_token", "")


async def twilio_auth_token_for_call(call_id: str) -> str:
    call = await db.calls.find_one({"id": call_id}, {"_id": 0, "org_id": 1})
    if not call:
        return ""
    return await twilio_auth_token_for_org(call["org_id"])


async def validate_twilio_request(request, auth_token: str) -> bool:
    """Verify Twilio's X-Twilio-Signature (HMAC-SHA1 over the public URL + sorted POST params).
    Fail-OPEN when validation is disabled, no auth token is configured, or on any internal error
    (never break a legitimate call due to a bug); reject only on a definitive mismatch / missing sig."""
    if not twilio_signature_enabled():
        return True
    try:
        if not auth_token:
            return True  # cannot validate (Twilio not fully configured) -> allow
        sig = request.headers.get("X-Twilio-Signature", "")
        if not sig:
            return False
        url = public_base_url() + request.url.path
        if request.url.query:
            url += "?" + request.url.query
        try:
            form = await request.form()
            params = {k: v for k, v in form.items()}
        except Exception:
            params = {}
        expected = _compute_twilio_sig(auth_token, url, params)
        return hmac.compare_digest(expected, sig)
    except Exception as e:
        logger.error(f"twilio signature validate error (fail-open): {e}")
        return True


# In-memory per-IP rate limiter for the public inbound webhook (cost-abuse protection).
_RATE = {}


def rate_limited(key: str, limit: int = 20, window: int = 60) -> bool:
    now = _time.time()
    hits = [t for t in _RATE.get(key, []) if now - t < window]
    hits.append(now)
    _RATE[key] = hits
    return len(hits) > limit


async def _store_audio(call_id: str, raw: bytes) -> str:
    token = f"{call_id}_{uuid4().hex[:10]}"
    await db.tts_audio.insert_one({"token": token, "call_id": call_id, "data": Binary(raw), "created_at": _now()})
    return token


async def _speak(org: dict, voice_id: str, text: str, call_id: str) -> str:
    """Synthesise `text` in the campaign voice (fast flash model) and return TwiML that plays it.
    Falls back to Twilio <Say> (en-GB) if ElevenLabs is unavailable — text is still script-driven."""
    text = (text or "").strip() or "One moment please."
    if voice_id:
        try:
            tts = await generate_tts(org, voice_id, text, model="eleven_flash_v2_5")
            url = tts.get("audio_url")
            if url and url.startswith("data:audio"):
                raw = base64.b64decode(url.split(",", 1)[1])
                token = await _store_audio(call_id, raw)
                return f"<Play>{escape(public_base_url())}/api/telephony/twilio/audio/{token}.mp3</Play>"
        except Exception as e:
            logger.error(f"twilio TTS failed, falling back to <Say>: {e}")
    return f'<Say voice="Polly.Amy" language="en-GB">{escape(text)}</Say>'


def _prompt_gather(inner: str, call_id: str) -> str:
    """Wrap the spoken prompt in a <Gather> so the prospect can BARGE IN (talk over the AI).
    actionOnEmptyResult keeps the loop alive on silence; speechTimeout='auto' ends the turn
    quickly on a natural pause."""
    base = public_base_url()
    action = f"{base}/api/telephony/twilio/turn/{call_id}"
    return (f'<Gather input="speech" action="{escape(action)}" method="POST" '
            f'language="en-GB" speechTimeout="auto" speechModel="experimental_conversations" '
            f'actionOnEmptyResult="true" timeout="6">{inner}</Gather>')


def _twiml(body: str) -> Response:
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


CLOSE_HINTS = ("goodbye", "bye for now", "have a great day", "take care", "remove you", "removed you", "won't call")


def build_twilio_voice_router():
    router = APIRouter(prefix="/api/telephony/twilio", tags=["twilio-voice"])

    @router.get("/audio/{token}.mp3")
    async def serve_audio(token: str):
        doc = await db.tts_audio.find_one({"token": token})
        if not doc:
            return Response(status_code=404)
        return Response(content=bytes(doc["data"]), media_type="audio/mpeg")

    @router.api_route("/voice/{call_id}", methods=["GET", "POST"])
    async def voice(call_id: str, request: Request):
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return _twiml('<Say voice="Polly.Amy">Sorry, this call could not be set up.</Say><Hangup/>')
        if not await validate_twilio_request(request, await twilio_auth_token_for_org(call["org_id"])):
            return Response(status_code=403)
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
        opening = call.get("opening") or (call.get("transcript") or [{}])[0].get("content") or "Hello, do you have a quick moment?"
        await db.calls.update_one({"id": call_id}, {"$set": {"status": "in_progress", "answered_at": _now()}})
        spoken = await _speak(org, call.get("voice_id"), opening, call_id)
        return _twiml(_prompt_gather(spoken, call_id))

    @router.post("/turn/{call_id}")
    async def turn(call_id: str, request: Request):
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return _twiml('<Hangup/>')
        if not await validate_twilio_request(request, await twilio_auth_token_for_org(call["org_id"])):
            return Response(status_code=403)
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
        form = await request.form()
        said = (form.get("SpeechResult") or "").strip()

        transcript = call.get("transcript") or []
        if not said:
            # No speech captured. Prompt once, then hang up on repeated silence.
            silences = call.get("silences", 0) + 1
            await db.calls.update_one({"id": call_id}, {"$set": {"silences": silences}})
            if silences >= 2:
                bye = "I'll let you go for now. Thanks for your time — goodbye."
                transcript.append({"role": "agent", "content": bye, "ts": _now()})
                await db.calls.update_one({"id": call_id}, {"$set": {"transcript": transcript}})
                return _twiml(await _speak(org, call.get("voice_id"), bye, call_id) + "<Hangup/>")
            prompt = "Sorry, I didn't quite catch that — are you still there?"
            return _twiml(_prompt_gather(await _speak(org, call.get("voice_id"), prompt, call_id), call_id))

        await db.calls.update_one({"id": call_id}, {"$set": {"silences": 0}})
        transcript.append({"role": "prospect", "content": said, "ts": _now()})

        reply = await agent_reply(
            call.get("script_content", ""), transcript, said, session_id=call_id,
            script_type=call.get("script_type", "line_by_line"), personality=call.get("personality", ""),
            company_overview=call.get("company_overview", ""), org=org)
        reply = (reply or "").strip() or "Thank you."
        transcript.append({"role": "agent", "content": reply, "ts": _now()})
        await db.calls.update_one({"id": call_id}, {"$set": {"transcript": transcript}})

        low = f"{said} {reply}".lower()
        ending = any(h in low for h in CLOSE_HINTS) or any(k in said.lower() for k in ("not interested", "opt out", "stop calling", "do not call", "remove me"))
        spoken = await _speak(org, call.get("voice_id"), reply, call_id)
        if ending:
            return _twiml(spoken + "<Hangup/>")
        return _twiml(_prompt_gather(spoken, call_id))

    @router.post("/status/{call_id}")
    async def status_cb(call_id: str, request: Request):
        if not await validate_twilio_request(request, await twilio_auth_token_for_call(call_id)):
            return Response(status_code=403)
        form = await request.form()
        cstatus = form.get("CallStatus", "")
        updates = {"provider_status": cstatus, "updated_at": _now()}
        if cstatus in ("completed", "busy", "no-answer", "failed", "canceled"):
            call = await db.calls.find_one({"id": call_id}, {"_id": 0})
            if call and not call.get("analysis"):
                transcript = call.get("transcript", []) or []
                answered = any(m.get("role") == "prospect" for m in transcript)
                is_vm = bool(call.get("voicemail"))
                if cstatus == "completed" and answered and not is_vm:
                    org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
                    tx = "\n".join([f"{m['role']}: {m['content']}" for m in transcript])
                    eb = call.get("ended_by") or "prospect_hangup"
                    out = "callback" if call.get("is_callback") else "answered"
                    try:
                        analysis = await analyze_transcript(tx, session_id=call_id, org=org)
                        updates.update({"analysis": analysis, "summary": analysis.get("summary"),
                                        "sentiment": analysis.get("sentiment"), "rating": analysis.get("score"),
                                        "status": "completed", "outcome": out, "ended_by": eb})
                    except Exception as e:
                        logger.error(f"twilio status analyze failed: {e}")
                        updates.update({"status": "completed", "outcome": out, "ended_by": eb})
                else:
                    # Not answered / voicemail — mark as no answer, do NOT rate.
                    eb = call.get("ended_by") or (cstatus.replace("-", "_") if cstatus != "completed" else "no_answer")
                    updates.update({"status": "no_answer",
                                    "outcome": "voicemail" if is_vm else "no_answer",
                                    "ended_by": eb})
            # Free the call's synthesised audio.
            try:
                await db.tts_audio.delete_many({"call_id": call_id})
            except Exception:
                pass
        await db.calls.update_one({"id": call_id}, {"$set": updates})
        return Response(status_code=204)

    @router.post("/amd/{call_id}")
    async def amd_cb(call_id: str, request: Request):
        """Async Answering Machine Detection result. When Twilio reports the call was answered
        by a machine/voicemail, we tag the call and end it automatically."""
        if not await validate_twilio_request(request, await twilio_auth_token_for_call(call_id)):
            return Response(status_code=403)
        form = await request.form()
        answered_by = (form.get("AnsweredBy") or "").strip()
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return Response(status_code=204)
        updates = {"answered_by": answered_by, "updated_at": _now()}
        is_machine = answered_by.startswith("machine") or answered_by == "fax"
        if is_machine:
            tx = call.get("transcript", []) or []
            tx.append({"role": "system",
                       "content": f"Voicemail / answering machine detected ({answered_by}) — call ended automatically.",
                       "ts": _now()})
            updates.update({"voicemail": True, "outcome": "voicemail", "status": "no_answer",
                            "ended_by": "voicemail", "transcript": tx})
            sid = call.get("provider_call_sid") or call.get("callid")
            if call.get("provider") == "twilio" and sid:
                org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
                integ = (org or {}).get("integrations", {})
                try:
                    from telephony import twilio_hangup_call
                    await twilio_hangup_call(integ, sid)
                except Exception as e:
                    logger.error(f"AMD auto-hangup failed for {call_id}: {e}")
            try:
                await db.tts_audio.delete_many({"call_id": call_id})
            except Exception:
                pass
        await db.calls.update_one({"id": call_id}, {"$set": updates})
        return Response(status_code=204)

    return router
