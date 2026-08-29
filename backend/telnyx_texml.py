"""Telnyx TeXML ConversationRelay — built-in, low-latency, interruptible AI voice calls.

This is the Telnyx analogue of conversation_relay.py (Twilio ConversationRelay): Telnyx
handles STT + TTS + turn-taking natively and exchanges the SAME JSON frames over a WebSocket
(`setup` / `prompt` / `interrupt` / `dtmf` → `text` / `end`). We only stream our workspace LLM.

Outbound flow:
  place_outbound_call -> telnyx_texml_make_call (POST /v2/texml/calls/{app_id}) ->
  Telnyx fetches our TeXML (`/texml/{call_id}`) -> <Connect><ConversationRelay url=wss.../> ->
  Telnyx opens the relay WS to us (`/relay/ws/{call_id}`) -> we run the LLM turn loop.

TTS: Telnyx native voices (default) OR ElevenLabs (voice string `ElevenLabs.<model>.<voiceId>`,
requires the org's ElevenLabs key stored as a Telnyx Integration Secret). Inworld is NOT
available inside ConversationRelay. STT: Telnyx built-in (Deepgram) — gives true two-way.

No auth on the relay WS — Telnyx calls it, keyed by the unguessable call id.
"""
import os
import json
import time
import asyncio
import logging
import uuid
import httpx
from datetime import datetime, timezone
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response

from database import db
from integrations import stream_agent_reply, analyze_transcript, get_voice

logger = logging.getLogger("telnyx_texml")
TELNYX = "https://api.telnyx.com/v2"

AGENT_CLOSE = ("goodbye", "good bye", "have a great day", "have a lovely day", "have a good day",
               "have a nice day", "thanks for your time", "thank you for your time", "take care",
               "bye for now", "speak soon", "we'll be in touch", "i'll let you go")
OPTOUT_HINTS = ("not interested", "opt out", "opt-out", "stop calling", "do not call",
                "remove me", "take me off", "don't call me")
_CR_ELEVEN_MODELS = {"eleven_flash_v2", "eleven_flash_v2_5", "eleven_turbo_v2", "eleven_turbo_v2_5",
                     "eleven_multilingual_v2"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def public_base_url() -> str:
    from twilio_voice import public_base_url as _b
    return _b()


def public_ws_url() -> str:
    base = public_base_url()
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):]
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):]
    return base


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"}


def _cr_eleven_model(integ: dict) -> str:
    m = integ.get("elevenlabs_model") or "eleven_flash_v2_5"
    return m if m in _CR_ELEVEN_MODELS else "eleven_flash_v2_5"


def _relay_voice(org: dict, voice_id: str) -> str:
    """Resolve the ConversationRelay `voice` string from org settings.

    - Telnyx native (default): `telnyx_native_voice` (e.g. 'Telnyx.Natural.abbie').
    - ElevenLabs: `ElevenLabs.<model>.<elevenlabs_voice_id>` — needs the ElevenLabs key stored
      as a Telnyx Integration Secret. Falls back to the Telnyx native voice if no EL voice id.
    """
    integ = (org or {}).get("integrations", {})
    native = integ.get("telnyx_native_voice") or "Telnyx.Natural.abbie"
    if (integ.get("telnyx_tts_provider") or "telnyx").lower() == "elevenlabs":
        v = get_voice(voice_id, org) if voice_id else None
        el_voice = (v or {}).get("elevenlabs_voice_id") or integ.get("elevenlabs_custom_voice_id")
        if el_voice:
            model = _cr_eleven_model(integ)
            logger.info(f"telnyx CR TTS -> ElevenLabs {model}.{el_voice}")
            return f"ElevenLabs.{model}.{el_voice}"
        logger.info("telnyx CR TTS -> ElevenLabs requested but no voice id; using Telnyx native.")
    return native


def _relay_texml(call_id: str, opening: str, voice_id: str, org: dict) -> str:
    ws_url = f"{public_ws_url()}/api/telephony/telnyx/relay/ws/{call_id}"
    action = f"{public_base_url()}/api/telephony/telnyx/texml/ended/{call_id}"
    voice = _relay_voice(org, voice_id)
    greeting = (opening or "Hello, do you have a quick moment?").strip()
    cr = (
        f'<ConversationRelay url={quoteattr(ws_url)} '
        f'welcomeGreeting={quoteattr(greeting)} '
        f'voice={quoteattr(voice)} language="en" transcriptionProvider="deepgram" '
        f'interruptible="any" welcomeGreetingInterruptible="any" dtmfDetection="true">'
        f'<Parameter name="call_id" value={quoteattr(call_id)} />'
        f'</ConversationRelay>'
    )
    return (f'<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Connect action={quoteattr(action)}>{cr}</Connect></Response>')


async def telnyx_texml_make_call(integ: dict, destination: str, call_id: str) -> dict:
    """Place an outbound TeXML ConversationRelay call.

    We pass the TeXML **inline** (`Texml` body field) instead of a fetch `Url`, so Telnyx
    executes our ConversationRelay directly and never fetches the application's Voice URL
    (that fetch was returning the app's root page -> 'application error'). Returns {callid, status}.
    """
    key = integ.get("telnyx_api_key") or os.environ.get("TELNYX_API_KEY", "")
    app_id = integ.get("telnyx_texml_app_id", "")
    frm = integ.get("telnyx_phone_number", "")
    if not (key and app_id and frm):
        raise ValueError("Telnyx TeXML is not fully configured (need API key, TeXML Application ID and phone number).")
    base = public_base_url()
    call = await db.calls.find_one({"id": call_id}, {"_id": 0})
    org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0}) if call else None
    inline_texml = _relay_texml(call_id, (call or {}).get("opening"), (call or {}).get("voice_id"), org)
    payload = {
        "To": destination, "From": frm, "ApplicationSid": app_id,
        "Texml": inline_texml,
        "FallbackUrl": f"{base}/api/telephony/telnyx/texml/fallback",
        "StatusCallback": f"{base}/api/telephony/telnyx/texml/status/{call_id}",
        "StatusCallbackMethod": "POST",
        "StatusCallbackEvent": "initiated ringing answered completed",
        "MachineDetection": "DetectMessageEnd", "DetectionMode": "Premium",
        "AsyncAmd": "true",
        "AsyncAmdStatusCallback": f"{base}/api/telephony/telnyx/texml/amd/{call_id}",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{TELNYX}/texml/calls/{app_id}", headers=_headers(key), json=payload)
    logger.info(f"telnyx texml dial {call_id} to={destination} -> HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise ValueError(f"Telnyx TeXML dial failed ({r.status_code}): {r.text[:200]}")
    try:
        data = r.json().get("data", r.json())
    except Exception:
        data = {}
    sid = data.get("call_sid") or data.get("call_control_id") or data.get("sid")
    return {"callid": sid, "status": "Initiated"}


def build_telnyx_texml_router() -> APIRouter:
    router = APIRouter(prefix="/api/telephony/telnyx", tags=["telnyx-texml"])

    @router.api_route("/texml/fallback", methods=["GET", "POST"])
    async def texml_fallback(request: Request):
        # Static, always-valid TeXML — safe value for the TeXML Application's Voice/Fallback URL
        # (we normally pass instructions inline, so this is only hit as a safety net).
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response>'
                        '<Say voice="Telnyx.Natural.abbie">Sorry, we could not connect your call right now. Goodbye.</Say>'
                        '<Hangup/></Response>', media_type="application/xml")

    @router.api_route("/texml/{call_id}", methods=["GET", "POST"])
    async def texml_instructions(call_id: str, request: Request):
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response>'
                            '<Say>Sorry, this call could not be set up.</Say><Hangup/></Response>',
                            media_type="application/xml")
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
        # Only stamp answered_at once — Telnyx may re-fetch the TeXML URL (retries).
        await db.calls.update_one({"id": call_id, "answered_at": {"$exists": False}},
                                  {"$set": {"status": "in_progress", "answered_at": _now()}})
        return Response(content=_relay_texml(call_id, call.get("opening"), call.get("voice_id"), org),
                        media_type="application/xml")

    @router.api_route("/texml/ended/{call_id}", methods=["GET", "POST"])
    async def texml_ended(call_id: str):
        # ConversationRelay finished (we sent `end`, or the caller hung up) — end the call.
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
                        media_type="application/xml")

    @router.api_route("/texml/status/{call_id}", methods=["GET", "POST"])
    async def texml_status(call_id: str, request: Request):
        form = await request.form()
        status = (form.get("CallStatus") or "").lower()
        logger.info(f"telnyx texml status {call_id}: {status}")
        if status == "answered":
            await db.calls.update_one({"id": call_id, "answered_at": {"$exists": False}},
                                      {"$set": {"status": "in_progress", "answered_at": _now()}})
        if status in ("busy", "no-answer", "failed", "canceled"):
            cur = await db.calls.find_one({"id": call_id}, {"_id": 0, "status": 1, "analysis": 1})
            if cur and cur.get("status") not in ("completed", "no_answer") and not cur.get("analysis"):
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "status": "no_answer", "outcome": status.replace("-", "_"),
                    "ended_by": status.replace("-", "_")}})
        return Response(status_code=204)

    @router.api_route("/texml/amd/{call_id}", methods=["GET", "POST"])
    async def texml_amd(call_id: str, request: Request):
        form = await request.form()
        result = (form.get("Result") or form.get("AnsweredBy") or "").lower()
        is_machine = "machine" in result or result == "fax"
        await db.calls.update_one({"id": call_id}, {"$set": {"answered_by": result}})
        if is_machine:
            await db.calls.update_one({"id": call_id}, {"$set": {
                "voicemail": True, "outcome": "voicemail", "status": "no_answer", "ended_by": "voicemail"}})
        return Response(status_code=204)

    @router.websocket("/relay/ws/{call_id}")
    async def relay_ws(ws: WebSocket, call_id: str):
        await ws.accept()
        ctx = {"loaded": False, "org": None, "transcript": [], "call": None}
        state = {"task": None, "pending": "", "speaking": False, "closing": False, "ended_by": None}

        async def _load():
            call = await db.calls.find_one({"id": call_id}, {"_id": 0})
            if not call:
                return False
            org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
            try:
                from routes import attach_system_prefix
                org = await attach_system_prefix(org, "call")
            except Exception:
                pass
            ctx["call"] = call
            ctx["org"] = org
            ctx["transcript"] = list(call.get("transcript") or [])
            ctx["loaded"] = True
            return True

        async def _persist():
            await db.calls.update_one({"id": call_id}, {"$set": {"transcript": list(ctx["transcript"])}})

        async def _finalise():
            if not ctx["loaded"]:
                return  # Telnyx connected then dropped before `setup` — nothing to finalise.
            transcript = list(ctx["transcript"])
            call = await db.calls.find_one({"id": call_id}, {"_id": 0}) or ctx["call"] or {}
            if call.get("status") in ("completed", "no_answer"):
                return  # already finalised by a status/AMD callback — don't clobber.
            answered = any(m.get("role") == "prospect" for m in transcript)
            is_vm = bool(call.get("voicemail"))
            eb = state.get("ended_by")
            if is_vm or not answered:
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "status": "no_answer", "outcome": "voicemail" if is_vm else "no_answer",
                    "suspected_voicemail": (not is_vm) and bool(call.get("answered_at")),
                    "ended_by": eb or ("voicemail" if is_vm else "no_answer"), "transcript": transcript}})
                return
            tx = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)
            org = ctx["org"] or await db.organizations.find_one({"id": call.get("org_id")}, {"_id": 0})
            try:
                analysis = await analyze_transcript(tx, session_id=call_id, org=org)
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "analysis": analysis, "summary": analysis.get("summary"),
                    "sentiment": analysis.get("sentiment"), "rating": analysis.get("score"),
                    "status": "completed", "outcome": "callback" if call.get("is_callback") else "answered",
                    "ended_by": eb or "prospect_hangup", "transcript": transcript,
                    "provider_path": "telnyx+conversationrelay"}})
            except Exception as e:
                logger.error(f"telnyx texml finalise failed: {e}")

        async def _handle_prompt(said: str):
            said = (said or "").strip()
            if not said or not ctx["loaded"]:
                return
            state["speaking"] = True
            try:
                call = ctx["call"]
                ctx["transcript"].append({"role": "prospect", "content": said, "ts": _now()})
                parts = []

                async def _send(txt):
                    await ws.send_text(json.dumps({"type": "text", "token": txt, "last": False}))

                try:
                    async for chunk in stream_agent_reply(
                            call.get("script_content", ""), ctx["transcript"], said, session_id=call_id,
                            script_type=call.get("script_type", "line_by_line"),
                            personality=call.get("personality", ""),
                            company_overview=call.get("company_overview", ""), org=ctx["org"], brief=True):
                        if chunk:
                            parts.append(chunk)
                            await _send(chunk)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"telnyx texml stream_agent_reply failed: {e}")
                reply = ("".join(parts)).strip() or "Sorry, could you say that again?"
                await ws.send_text(json.dumps({"type": "text", "token": "", "last": True}))
                ctx["transcript"].append({"role": "agent", "content": reply, "ts": _now()})
                await _persist()
                optout = any(k in said.lower() for k in OPTOUT_HINTS)
                goodbye = any(h in reply.lower() for h in AGENT_CLOSE)
                if optout or goodbye:
                    state["closing"] = True
                    state["ended_by"] = "prospect_optout" if optout else "agent"
                    await asyncio.sleep(0.4)
                    await ws.send_text(json.dumps({"type": "end"}))
            finally:
                state["speaking"] = False

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "setup":
                    ok = await _load()
                    if ok:
                        await db.calls.update_one({"id": call_id}, {"$set": {
                            "status": "in_progress",
                            "provider_call_sid": msg.get("callControlId") or msg.get("callSid"),
                            "relay_session": msg.get("sessionId"), "updated_at": _now()}})
                        await db.calls.update_one({"id": call_id, "answered_at": {"$exists": False}},
                                                  {"$set": {"answered_at": _now()}})
                elif mtype == "prompt":
                    if state["task"] and not state["task"].done():
                        state["task"].cancel()
                    txt = (msg.get("voicePrompt") or "").strip()
                    if txt:
                        state["pending"] = (state["pending"] + " " + txt).strip()
                    if msg.get("last", True) and state["pending"]:
                        said = state["pending"]
                        state["pending"] = ""
                        state["task"] = asyncio.create_task(_handle_prompt(said))
                elif mtype == "interrupt":
                    if state["task"] and not state["task"].done():
                        state["task"].cancel()
                elif mtype == "error":
                    logger.error(f"telnyx texml relay error {call_id}: {msg}")
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"telnyx texml relay ws exception {call_id}: {e}")
        finally:
            if state["task"] and not state["task"].done():
                state["task"].cancel()
            await _finalise()

    return router
