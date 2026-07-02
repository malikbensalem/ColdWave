"""Twilio Programmable Voice webhooks that run a turn-based AI cold call using the
campaign's script/blueprint + ElevenLabs voice — the same generation pipeline as Test Calls.

Twilio fetches the call's `Url` (voice webhook) → we <Play> the ElevenLabs opening and
<Gather input="speech"> the prospect's reply → the turn webhook feeds it to agent_reply,
synthesises the response in the campaign voice, and gathers again until hangup/opt-out.
No auth on these routes — Twilio calls them; they are keyed by the (unguessable) call id.
"""
import os
import base64
import logging
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from database import db
from integrations import generate_tts, agent_reply, analyze_transcript

logger = logging.getLogger("twilio_voice")

# In-memory audio cache: token -> mp3 bytes (served to Twilio via a public URL).
_AUDIO: dict = {}


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


async def _speak(org: dict, voice_id: str, text: str, call_id: str) -> str:
    """Synthesise `text` in the campaign voice and return TwiML that plays it.
    Falls back to Twilio <Say> (en-GB) if ElevenLabs is unavailable — text is still script-driven."""
    text = (text or "").strip() or "One moment please."
    if voice_id:
        try:
            tts = await generate_tts(org, voice_id, text)
            url = tts.get("audio_url")
            if url and url.startswith("data:audio"):
                raw = base64.b64decode(url.split(",", 1)[1])
                token = f"{call_id}_{len(_AUDIO)}_{abs(hash(text)) % 100000}"
                _AUDIO[token] = raw
                # Keep the cache from growing unbounded.
                if len(_AUDIO) > 500:
                    for k in list(_AUDIO.keys())[:100]:
                        _AUDIO.pop(k, None)
                return f"<Play>{escape(public_base_url())}/api/telephony/twilio/audio/{token}.mp3</Play>"
        except Exception as e:
            logger.error(f"twilio TTS failed, falling back to <Say>: {e}")
    return f'<Say voice="Polly.Amy" language="en-GB">{escape(text)}</Say>'


def _gather(call_id: str) -> str:
    base = public_base_url()
    action = f"{base}/api/telephony/twilio/turn/{call_id}"
    return (f'<Gather input="speech" action="{escape(action)}" method="POST" '
            f'language="en-GB" speechTimeout="auto" timeout="7"></Gather>'
            f'<Redirect method="POST">{escape(action)}?silence=1</Redirect>')


def _twiml(body: str) -> Response:
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


CLOSE_HINTS = ("goodbye", "bye for now", "have a great day", "take care", "remove you", "removed you", "won't call")


def build_twilio_voice_router():
    router = APIRouter(prefix="/api/telephony/twilio", tags=["twilio-voice"])

    @router.get("/audio/{token}.mp3")
    async def serve_audio(token: str):
        data = _AUDIO.get(token)
        if not data:
            return Response(status_code=404)
        return Response(content=data, media_type="audio/mpeg")

    @router.api_route("/voice/{call_id}", methods=["GET", "POST"])
    async def voice(call_id: str):
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return _twiml('<Say voice="Polly.Amy">Sorry, this call could not be set up.</Say><Hangup/>')
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
        opening = call.get("opening") or (call.get("transcript") or [{}])[0].get("content") or "Hello, do you have a quick moment?"
        await db.calls.update_one({"id": call_id}, {"$set": {"status": "in_progress", "answered_at": _now()}})
        return _twiml(await _speak(org, call.get("voice_id"), opening, call_id) + _gather(call_id))

    @router.post("/turn/{call_id}")
    async def turn(call_id: str, request: Request):
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return _twiml('<Hangup/>')
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
        form = await request.form()
        said = (form.get("SpeechResult") or "").strip()
        silence = request.query_params.get("silence")

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
            return _twiml(await _speak(org, call.get("voice_id"), prompt, call_id) + _gather(call_id))

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
        twiml = await _speak(org, call.get("voice_id"), reply, call_id)
        return _twiml(twiml + ("<Hangup/>" if ending else _gather(call_id)))

    @router.post("/status/{call_id}")
    async def status_cb(call_id: str, request: Request):
        form = await request.form()
        cstatus = form.get("CallStatus", "")
        updates = {"provider_status": cstatus, "updated_at": _now()}
        if cstatus in ("completed", "busy", "no-answer", "failed", "canceled"):
            call = await db.calls.find_one({"id": call_id}, {"_id": 0})
            if call and not call.get("analysis"):
                org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
                tx = "\n".join([f"{m['role']}: {m['content']}" for m in call.get("transcript", [])])
                try:
                    analysis = await analyze_transcript(tx, session_id=call_id, org=org)
                    updates.update({"analysis": analysis, "summary": analysis.get("summary"),
                                    "sentiment": analysis.get("sentiment"), "rating": analysis.get("score"),
                                    "status": "completed"})
                except Exception as e:
                    logger.error(f"twilio status analyze failed: {e}")
                    updates["status"] = "completed"
        await db.calls.update_one({"id": call_id}, {"$set": updates})
        return Response(status_code=204)

    return router
