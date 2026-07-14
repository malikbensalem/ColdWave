"""Twilio ConversationRelay — real-time, interruptible AI voice calls over a WebSocket.

ConversationRelay opens a persistent wss connection: Twilio does built-in speech-to-text,
streams us the caller's words as `prompt` events, we stream the workspace's LLM reply back
as `text` for Twilio to speak. Barge-in is handled by Twilio (interruptible) plus an
`interrupt` event that cancels the in-flight LLM turn — low latency, interruptible AI.

Latency optimisations:
  - The call context (script/voice/company overview) + org are loaded ONCE on `setup` and
    cached on the connection — no DB round-trips on the hot path before the LLM starts.
  - The LLM reply is streamed token-by-token AND kept brief (one/two sentences) so audio
    starts within a few hundred ms and finishes fast.
  - Transcript persistence happens off the hot path (fire-and-forget).

No auth on these routes — Twilio calls them; they are keyed by the (unguessable) call id.
"""
import time
import json
import re
import asyncio
import logging
from datetime import datetime, timezone
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from database import db
from models import new_id
from integrations import stream_agent_reply, analyze_transcript, get_voice

logger = logging.getLogger("conversation_relay")

CLOSE_HINTS = ("goodbye", "bye for now", "have a great day", "take care", "remove you",
               "removed you", "won't call", "won't contact")
OPTOUT_HINTS = ("not interested", "opt out", "stop calling", "do not call", "remove me")
_SENTENCE_END = re.compile(r'[.!?…]+["\')\]]*(\s|$)')

# Google en-GB voices for Twilio's built-in TTS (no extra account config needed).
_VOICE_BY_GENDER = {"male": "en-GB-Standard-B", "female": "en-GB-Standard-A"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def public_ws_url() -> str:
    from twilio_voice import public_base_url
    base = public_base_url()
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):]
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):]
    return base


def _relay_voice(voice_id: str) -> str:
    v = get_voice(voice_id) if voice_id else None
    gender = (v or {}).get("gender", "female")
    return _VOICE_BY_GENDER.get(gender, "en-GB-Standard-A")


def _relay_twiml(call_id: str, opening: str, voice_id: str) -> str:
    ws_url = f"{public_ws_url()}/api/telephony/twilio/relay/ws/{call_id}"
    voice = _relay_voice(voice_id)
    cr = (
        f'<ConversationRelay url={quoteattr(ws_url)} '
        f'welcomeGreeting={quoteattr((opening or "Hello, do you have a quick moment?").strip())} '
        f'welcomeGreetingInterruptible="true" interruptible="any" '
        f'reportInputDuringAgentSpeech="speech" dtmfDetection="true" '
        f'voice={quoteattr(voice)} language="en-GB" />'
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect>{cr}</Connect></Response>'


def build_conversation_relay_router():
    router = APIRouter(prefix="/api/telephony/twilio/relay", tags=["twilio-relay"])

    @router.api_route("/voice/{call_id}", methods=["GET", "POST"])
    async def relay_voice(call_id: str):
        """TwiML for OUTBOUND calls — connects the pre-created call to our WebSocket."""
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response>'
                        '<Say voice="Polly.Amy">Sorry, this call could not be set up.</Say><Hangup/></Response>',
                media_type="application/xml")
        await db.calls.update_one({"id": call_id}, {"$set": {"status": "in_progress", "answered_at": _now()}})
        return Response(content=_relay_twiml(call_id, call.get("opening"), call.get("voice_id")),
                        media_type="application/xml")

    @router.api_route("/incoming", methods=["GET", "POST"])
    async def relay_incoming(request: Request):
        """Stable webhook to paste into the Twilio Console (Phone Number → Voice → 'A call comes in').
        Builds an AI call on the fly for INBOUND calls and connects them to the streaming agent."""
        form = await request.form()
        to = (form.get("To") or "").strip()
        frm = (form.get("From") or "").strip()
        call_sid = (form.get("CallSid") or "").strip()
        org = await db.organizations.find_one({"integrations.twilio_phone_number": to}, {"_id": 0}) \
            or await db.organizations.find_one({}, {"_id": 0})
        if not org:
            return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response>'
                            '<Say>Service is not configured.</Say><Hangup/></Response>', media_type="application/xml")
        camp = (await db.campaigns.find_one({"org_id": org["id"], "status": "active"}, {"_id": 0})
                or await db.campaigns.find_one({"org_id": org["id"]}, {"_id": 0}))
        from routes import build_campaign_call_context
        ctx = await build_campaign_call_context(org, camp)
        call_id = new_id("call")
        await db.calls.insert_one({
            "id": call_id, "org_id": org["id"], "type": "inbound", "is_test": False,
            "campaign_id": (camp or {}).get("id"), "destination": frm, "provider": "twilio",
            "provider_call_sid": call_sid, "status": "in_progress",
            "voice_id": ctx["voice_id"], "voice_name": ctx["voice_name"], "script_id": ctx["script_id"],
            "script_content": ctx["script_content"], "script_type": ctx["script_type"],
            "personality": ctx["personality"], "company_overview": ctx["company_overview"],
            "opening": ctx["opening"],
            "transcript": [{"role": "agent", "content": ctx["opening"], "ts": _now()}],
            "created_at": _now(), "answered_at": _now(),
        })
        return Response(content=_relay_twiml(call_id, ctx["opening"], ctx["voice_id"]),
                        media_type="application/xml")

    @router.websocket("/ws/{call_id}")
    async def relay_ws(ws: WebSocket, call_id: str):
        await ws.accept()
        # Connection-scoped cache — loaded once on setup, no DB reads on the hot path.
        ctx = {"loaded": False, "org": None, "transcript": [], "call": None}
        state = {"task": None}

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

        async def _persist_transcript():
            await db.calls.update_one({"id": call_id}, {"$set": {"transcript": list(ctx["transcript"])}})

        async def _finalise():
            tx = "\n".join([f"{m['role']}: {m['content']}" for m in ctx["transcript"]])
            if not tx.strip():
                return
            org = ctx["org"] or await db.organizations.find_one({"id": (ctx["call"] or {}).get("org_id")}, {"_id": 0})
            try:
                analysis = await analyze_transcript(tx, session_id=call_id, org=org)
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "analysis": analysis, "summary": analysis.get("summary"),
                    "sentiment": analysis.get("sentiment"), "rating": analysis.get("score"),
                    "transcript": list(ctx["transcript"])}})
            except Exception as e:
                logger.error(f"relay finalise analyze failed: {e}")

        async def _warmup():
            # Warm the LLM connection pool while the caller hears the greeting, so the
            # FIRST real turn is fast too (avoids the cold-start TLS/connection penalty).
            try:
                async for _ in stream_agent_reply(
                    "warmup", [{"role": "agent", "content": "hi"}], "hi", session_id=call_id + "_warm",
                    org=ctx["org"], brief=True):
                    break
            except Exception:
                pass

        async def _handle_prompt(said: str):
            said = (said or "").strip()
            if not said or not ctx["loaded"]:
                return
            call = ctx["call"]
            ctx["transcript"].append({"role": "prospect", "content": said, "ts": _now()})
            integ = (ctx["org"] or {}).get("integrations", {})
            chunking = integ.get("llm_chunking", True)

            t0 = time.time()
            first_at = None
            parts = []
            buffer = ""

            async def _send(txt):
                await ws.send_text(json.dumps({"type": "text", "token": txt, "last": False}))

            try:
                async for chunk in stream_agent_reply(
                    call.get("script_content", ""), ctx["transcript"], said, session_id=call_id,
                    script_type=call.get("script_type", "line_by_line"),
                    personality=call.get("personality", ""),
                    company_overview=call.get("company_overview", ""), org=ctx["org"], brief=True):
                    if not chunk:
                        continue
                    if first_at is None:
                        first_at = time.time() - t0
                    parts.append(chunk)
                    if chunking:
                        # Emit complete sentences so long replies are spoken naturally
                        # (Twilio TTS gets whole clauses, not fragmented tokens).
                        buffer += chunk
                        while True:
                            m = _SENTENCE_END.search(buffer)
                            if not m:
                                break
                            sentence = buffer[:m.end()].strip()
                            buffer = buffer[m.end():]
                            if sentence:
                                await _send(sentence)
                    else:
                        await _send(chunk)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"relay stream_agent_reply failed: {e}")
            if chunking and buffer.strip():
                await _send(buffer.strip())
            reply = ("".join(parts)).strip()
            if not reply:
                reply = "Sorry, could you say that again?"
                await _send(reply)
            await ws.send_text(json.dumps({"type": "text", "token": "", "last": True}))
            logger.info(f"relay turn {call_id}: first_token={(first_at or 0):.2f}s full={time.time()-t0:.2f}s len={len(reply)}")

            ctx["transcript"].append({"role": "agent", "content": reply, "ts": _now()})
            await _persist_transcript()

            low = f"{said} {reply}".lower()
            ending = any(h in low for h in CLOSE_HINTS) or any(k in said.lower() for k in OPTOUT_HINTS)
            if ending:
                await asyncio.sleep(0.3)
                await ws.send_text(json.dumps({"type": "end"}))

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
                        asyncio.ensure_future(_warmup())
                        await db.calls.update_one({"id": call_id}, {"$set": {
                            "status": "in_progress", "provider_call_sid": msg.get("callSid"),
                            "relay_session": msg.get("sessionId"), "updated_at": _now()}})

                elif mtype == "prompt":
                    if state["task"] and not state["task"].done():
                        state["task"].cancel()
                    state["task"] = asyncio.create_task(_handle_prompt(msg.get("voicePrompt", "")))

                elif mtype == "interrupt":
                    if state["task"] and not state["task"].done():
                        state["task"].cancel()

                elif mtype == "error":
                    logger.error(f"relay error for {call_id}: {msg}")

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"relay ws exception {call_id}: {e}")
        finally:
            if state["task"] and not state["task"].done():
                state["task"].cancel()
            await _finalise()

    return router
