"""Telnyx media bridge — our own thin STT+TTS relay (parallel to conversation_relay.py).

Sole handler of the Telnyx call: bidirectional Media Streaming (8kHz PCMU), barge-in,
VAD gating, the LLM turn loop (stream_agent_reply), hangup/finalise logic.
Provider-agnostic per org: TTS via select_tts_provider (ElevenLabs ulaw_8000 OR Inworld
MULAW, through generate_tts_telephony); STT via select_stt_provider (Inworld Realtime —
the only streaming STT — or a clear error when none is configured). Cloud-managed APIs only.
"""
import os
import json
import base64
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import db
from integrations import (stream_agent_reply, analyze_transcript, generate_tts_inworld,
                          generate_tts_telephony, select_tts_provider, select_stt_provider,
                          INWORLD_STT_WS, _inworld_key)

try:
    import audioop  # stdlib (Py<3.13) or audioop-lts
    _HAS_AUDIOOP = True
except Exception:  # pragma: no cover
    _HAS_AUDIOOP = False

logger = logging.getLogger("telnyx_relay")

AGENT_CLOSE = ("goodbye", "have a great day", "have a lovely day", "thanks for your time",
               "thank you for your time", "take care", "bye for now", "i'll let you go")
OPTOUT_HINTS = ("not interested", "opt out", "stop calling", "do not call", "remove me", "take me off")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _pcmu_to_pcm16_16k(pcmu_bytes: bytes) -> bytes:
    """mu-law 8kHz -> signed 16-bit PCM 16kHz for Inworld STT (best accuracy)."""
    if not _HAS_AUDIOOP:
        return pcmu_bytes  # fallback: STT config will use 8k (reduced accuracy)
    pcm16 = audioop.ulaw2lin(pcmu_bytes, 2)
    pcm16_16k, _ = audioop.ratecv(pcm16, 2, 1, 8000, 16000, None)
    return pcm16_16k


def _rms(pcm16: bytes) -> int:
    if not _HAS_AUDIOOP or not pcm16:
        return 999
    try:
        return audioop.rms(pcm16, 2)
    except Exception:
        return 999


def build_telnyx_relay_router() -> APIRouter:
    router = APIRouter(prefix="/api/telephony/telnyx", tags=["telnyx-media"])

    @router.websocket("/media/{call_id}")
    async def telnyx_media(ws: WebSocket, call_id: str):
        await ws.accept()
        import websockets
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0}) if call else None
        if not call or not org:
            await ws.close()
            return
        integ = org.get("integrations", {})
        key = _inworld_key(org)
        tts_provider = select_tts_provider(org).get("provider")
        stt_sel = select_stt_provider(org)
        stt_provider = stt_sel.get("provider")
        voice_id = call.get("voice_id")
        sample_rate = 8000 if not _HAS_AUDIOOP else 16000
        transcript = list(call.get("transcript", []) or [])
        state = {"task": None, "speaking": False, "ended_by": None, "closing": False, "stt": None, "started": False}
        logger.info(f"telnyx relay {call_id}: tts_provider={tts_provider} stt_provider={stt_provider} voice={voice_id}")

        async def _send_audio_b64(b64_mulaw: str):
            # Telnyx expects base64 PCMU frames back on the same socket.
            await ws.send_text(json.dumps({"event": "media", "media": {"payload": b64_mulaw}}))

        async def _clear_playback():
            try:
                await ws.send_text(json.dumps({"event": "clear"}))
            except Exception:
                pass

        async def _speak(text: str):
            # Unified telephony TTS — Inworld or ElevenLabs (ulaw_8000), both cached.
            res = await generate_tts_telephony(org, text, voice_id=voice_id)
            if not res.get("audio_b64"):
                logger.error(f"telnyx relay {call_id} TTS FAILED ({res.get('provider')}): {res.get('error')}")
                return
            # Decode once to raw 8kHz PCMU, then send as 20ms (160-byte) frames, each base64'd,
            # on the same media stream. Slicing the base64 string directly corrupts frames.
            raw = base64.b64decode(res["audio_b64"])
            FRAME = 160  # 20ms of 8kHz mu-law
            n_frames = (len(raw) + FRAME - 1) // FRAME
            logger.info(f"telnyx relay {call_id}: SPEAK via {res.get('provider')} cached={res.get('cached')} "
                        f"rawbytes={len(raw)} frames={n_frames} text='{text[:48]}'")
            state["speaking"] = True
            loop = asyncio.get_event_loop()
            next_t = loop.time()
            for i in range(0, len(raw), FRAME):
                if state["closing"] or not state["speaking"]:
                    break
                frame = raw[i:i + FRAME]
                if len(frame) < FRAME:
                    frame = frame + b"\xff" * (FRAME - len(frame))  # mu-law silence pad
                payload = base64.b64encode(frame).decode()
                await ws.send_text(json.dumps({"event": "media", "media": {"payload": payload}}))
                # Monotonic 20ms pacing (avoids drift/slow playback on long replies).
                next_t += 0.02
                delay = next_t - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)

        async def _handle_final(said: str):
            said = (said or "").strip()
            if not said:
                return
            state["speaking"] = True
            try:
                transcript.append({"role": "prospect", "content": said, "ts": _now()})
                parts, buffer = [], ""
                async for chunk in stream_agent_reply(
                        call.get("script_content", ""), transcript, said, session_id=call_id,
                        script_type=call.get("script_type", "line_by_line"),
                        personality=call.get("personality", ""),
                        company_overview=call.get("company_overview", ""), org=org, brief=True):
                    if not chunk:
                        continue
                    parts.append(chunk)
                    buffer += chunk
                    if buffer.endswith((".", "!", "?", "…")) and len(buffer) > 8:
                        await _speak(buffer.strip())
                        buffer = ""
                if buffer.strip():
                    await _speak(buffer.strip())
                reply = "".join(parts).strip() or "Sorry, could you say that again?"
                transcript.append({"role": "agent", "content": reply, "ts": _now()})
                await db.calls.update_one({"id": call_id}, {"$set": {"transcript": transcript}})
                if any(k in said.lower() for k in OPTOUT_HINTS):
                    state["ended_by"] = "prospect_optout"; state["closing"] = True
                elif any(h in reply.lower() for h in AGENT_CLOSE):
                    state["ended_by"] = "agent"; state["closing"] = True
                if state["closing"]:
                    from telnyx_voice import telnyx_hangup
                    await asyncio.sleep(0.3)
                    await telnyx_hangup(integ, call.get("provider_call_sid") or "")
            finally:
                state["speaking"] = False

        async def _stt_reader(stt):
            async for raw in stt:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                t = (msg.get("result", {}) or {}).get("transcription") or {}
                if t.get("isFinal") and t.get("transcript"):
                    # Barge-in: stop any current reply, then respond to the final utterance.
                    if state["task"] and not state["task"].done():
                        state["task"].cancel()
                        await _clear_playback()
                    state["task"] = asyncio.create_task(_handle_final(t["transcript"]))

        async def _finalise():
            answered = any(m.get("role") == "prospect" for m in transcript)
            if not answered:
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "status": "no_answer", "outcome": "no_answer",
                    "ended_by": state["ended_by"] or "no_answer", "transcript": transcript}})
                return
            tx = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)
            try:
                analysis = await analyze_transcript(tx, session_id=call_id, org=org)
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "analysis": analysis, "summary": analysis.get("summary"),
                    "sentiment": analysis.get("sentiment"), "rating": analysis.get("score"),
                    "status": "completed", "outcome": "callback" if call.get("is_callback") else "answered",
                    "ended_by": state["ended_by"] or "prospect_hangup", "transcript": transcript,
                    "provider_path": f"telnyx+{tts_provider}"}})
            except Exception as e:
                logger.error(f"telnyx relay finalise failed: {e}")

        stt = None
        try:
            # STT only via Inworld (ElevenLabs has no STT). If not selected/keyed, the agent can
            # still speak (greeting/opening) but won't transcribe replies — logged clearly.
            if stt_provider == "inworld" and key:
                stt = await websockets.connect(INWORLD_STT_WS, additional_headers={"Authorization": f"Basic {key}"}, max_size=None)
                await stt.send(json.dumps({"transcribeConfig": {
                    "modelId": "inworld/inworld-stt-1", "audioEncoding": "LINEAR16",
                    "sampleRateHertz": sample_rate, "numberOfChannels": 1, "language": "en"}}))
                state["stt"] = stt
                asyncio.create_task(_stt_reader(stt))
            else:
                reason = stt_sel.get("reason", "not_configured")
                msg = ("No streaming STT is configured for this Telnyx call "
                       f"(reason: {reason}). The agent will play the opening but cannot hear "
                       "the prospect — enable Inworld STT in Settings for two-way conversation.")
                logger.error(f"telnyx relay {call_id}: {msg}")
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "stt_status": "disabled", "stt_error": msg}})
            # greeting
            opening = call.get("opening") or "Hello, do you have a quick moment?"

            async def _greet():
                state["speaking"] = True
                await _speak(opening)
                state["speaking"] = False
                transcript.append({"role": "agent", "content": opening, "ts": _now()})
                await db.calls.update_one({"id": call_id}, {"$set": {"transcript": transcript}})

            async def _greet_once(reason: str):
                if state["started"] or state["closing"]:
                    return
                state["started"] = True
                logger.info(f"telnyx relay {call_id}: playing greeting ({reason})")
                state["task"] = asyncio.create_task(_greet())

            async def _start_watchdog():
                # Safety net: if Telnyx's 'start' never arrives, greet anyway so the call
                # can't stay silent forever (mis-configured stream, dropped event, etc.).
                await asyncio.sleep(4)
                if not state["started"] and not state["closing"]:
                    logger.error(f"telnyx relay {call_id}: no 'start' event after 4s — greeting anyway")
                    await _greet_once("watchdog-fallback")

            asyncio.create_task(_start_watchdog())

            # Wait for Telnyx's "start" event before speaking — audio sent before the
            # bidirectional RTP stream is ready is silently dropped (the greeting is lost).
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                event = msg.get("event")
                if event == "connected":
                    logger.info(f"telnyx relay {call_id}: ws connected {msg.get('version', '')}")
                elif event == "start":
                    mf = (msg.get("start", {}) or {}).get("media_format", {})
                    logger.info(f"telnyx relay {call_id}: STREAM STARTED id={msg.get('stream_id')} "
                                f"media_format={mf}")
                    await _greet_once("start-event")
                elif event == "media":
                    if not stt:
                        continue
                    pcmu = base64.b64decode(msg["media"]["payload"])
                    pcm = _pcmu_to_pcm16_16k(pcmu)
                    if _rms(pcm) > 150:  # simple VAD — don't stream silence to STT
                        await stt.send(json.dumps({"audioChunk": {"content": base64.b64encode(pcm).decode()}}))
                elif event == "error":
                    logger.error(f"telnyx relay {call_id}: STREAM ERROR {msg.get('payload')}")
                elif event == "stop":
                    logger.info(f"telnyx relay {call_id}: stream stopped")
                    break
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"telnyx media ws error {call_id}: {e}")
        finally:
            if stt:
                try:
                    await stt.send(json.dumps({"closeStream": {}}))
                    await stt.close()
                except Exception:
                    pass
            if state["task"] and not state["task"].done():
                state["task"].cancel()
            await _finalise()

    return router
