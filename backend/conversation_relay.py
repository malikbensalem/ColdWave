"""Twilio ConversationRelay — real-time, interruptible AI voice calls over a WebSocket.

Instead of the turn-based <Gather> loop (twilio_voice.py), ConversationRelay opens a
persistent wss connection: Twilio does built-in speech-to-text, streams us the caller's
words as `prompt` events, we run the workspace's LLM (agent_reply) and stream the reply
back as `text` for Twilio to speak. Barge-in is handled by Twilio (interruptible) plus an
`interrupt` event that cancels the in-flight LLM turn — giving low latency, interruptible AI.

No auth on these routes — Twilio calls them; they are keyed by the (unguessable) call id.
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from database import db
from integrations import agent_reply, analyze_transcript, get_voice

logger = logging.getLogger("conversation_relay")

CLOSE_HINTS = ("goodbye", "bye for now", "have a great day", "take care", "remove you",
               "removed you", "won't call", "won't contact")
OPTOUT_HINTS = ("not interested", "opt out", "stop calling", "do not call", "remove me")

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


def build_conversation_relay_router():
    router = APIRouter(prefix="/api/telephony/twilio/relay", tags=["twilio-relay"])

    @router.api_route("/voice/{call_id}", methods=["GET", "POST"])
    async def relay_voice(call_id: str):
        """TwiML that connects the call to our ConversationRelay WebSocket."""
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        if not call:
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response>'
                        '<Say voice="Polly.Amy">Sorry, this call could not be set up.</Say><Hangup/></Response>',
                media_type="application/xml")
        opening = (call.get("opening") or "Hello, do you have a quick moment?").strip()
        await db.calls.update_one({"id": call_id},
                                  {"$set": {"status": "in_progress", "answered_at": _now()}})
        ws_url = f"{public_ws_url()}/api/telephony/twilio/relay/ws/{call_id}"
        voice = _relay_voice(call.get("voice_id"))
        cr = (
            f'<ConversationRelay url={quoteattr(ws_url)} '
            f'welcomeGreeting={quoteattr(opening)} welcomeGreetingInterruptible="true" '
            f'interruptible="any" reportInputDuringAgentSpeech="speech" dtmfDetection="true" '
            f'voice={quoteattr(voice)} language="en-GB" />'
        )
        xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect>{cr}</Connect></Response>'
        return Response(content=xml, media_type="application/xml")

    @router.websocket("/ws/{call_id}")
    async def relay_ws(ws: WebSocket, call_id: str):
        await ws.accept()
        state = {"task": None}

        async def _finalise():
            call = await db.calls.find_one({"id": call_id}, {"_id": 0})
            if call and not call.get("analysis"):
                org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
                tx = "\n".join([f"{m['role']}: {m['content']}" for m in call.get("transcript", [])])
                try:
                    analysis = await analyze_transcript(tx, session_id=call_id, org=org)
                    await db.calls.update_one({"id": call_id}, {"$set": {
                        "analysis": analysis, "summary": analysis.get("summary"),
                        "sentiment": analysis.get("sentiment"), "rating": analysis.get("score"),
                    }})
                except Exception as e:
                    logger.error(f"relay finalise analyze failed: {e}")

        async def _handle_prompt(said: str):
            said = (said or "").strip()
            if not said:
                return
            call = await db.calls.find_one({"id": call_id}, {"_id": 0})
            if not call:
                await ws.send_text(json.dumps({"type": "end"}))
                return
            # Human has taken over — stop the AI and let the human/handoff drive the call.
            if call.get("handoff"):
                await ws.send_text(json.dumps({"type": "end"}))
                return
            org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0})
            transcript = call.get("transcript") or []
            transcript.append({"role": "prospect", "content": said, "ts": _now()})
            await db.calls.update_one({"id": call_id}, {"$set": {"transcript": transcript}})

            try:
                reply = await agent_reply(
                    call.get("script_content", ""), transcript, said, session_id=call_id,
                    script_type=call.get("script_type", "line_by_line"),
                    personality=call.get("personality", ""),
                    company_overview=call.get("company_overview", ""), org=org)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"relay agent_reply failed: {e}")
                reply = "Sorry, could you say that again?"
            reply = (reply or "").strip() or "Thank you."
            transcript.append({"role": "agent", "content": reply, "ts": _now()})
            await db.calls.update_one({"id": call_id}, {"$set": {"transcript": transcript}})

            low = f"{said} {reply}".lower()
            ending = any(h in low for h in CLOSE_HINTS) or any(k in said.lower() for k in OPTOUT_HINTS)
            await ws.send_text(json.dumps({"type": "text", "token": reply, "last": True}))
            if ending:
                await asyncio.sleep(0.2)
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
