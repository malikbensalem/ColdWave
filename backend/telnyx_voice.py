"""Telnyx Programmable Voice — outbound AI calling via Call Control API.

Cloud-hosted managed API only (no self-hosting). Mirrors twilio_voice.py:
outbound dial, Ed25519 webhook signature verification, and Call Control event
handling (answer/AMD/streaming_start). All credentials are per-org.
"""
import os
import json
import time
import base64
import logging
import uuid
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response

from database import db

logger = logging.getLogger("telnyx_voice")
TELNYX = "https://api.telnyx.com/v2"


def telnyx_is_machine(result: str) -> bool:
    """True when AMD says voicemail/machine — used to short-circuit the AI pipeline."""
    result = (result or "").lower()
    return result in ("machine", "fax", "not_sure") or "machine" in result


def _now():
    return datetime.now(timezone.utc).isoformat()


def public_base_url() -> str:
    from twilio_voice import public_base_url as _b
    return _b()


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"}


async def telnyx_validate(integ: dict) -> dict:
    """Validate API key + connection id via GET /v2/connections/{id}."""
    key = integ.get("telnyx_api_key") or os.environ.get("TELNYX_API_KEY", "")
    conn = integ.get("telnyx_connection_id", "")
    if not key:
        return {"valid": False, "error": "No Telnyx API key provided."}
    if not conn:
        return {"valid": False, "error": "No Telnyx Connection ID provided."}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{TELNYX}/connections/{conn}", headers=_headers(key))
        if r.status_code != 200:
            return {"valid": False, "status": r.status_code, "error": r.text}
        data = r.json().get("data", {})
        return {"valid": True, "connection_id": data.get("id"), "record_type": data.get("record_type"),
                "active": data.get("active", True)}
    except Exception as e:
        return {"valid": False, "error": str(e)}


async def telnyx_make_call(integ: dict, destination: str, call_id: str) -> dict:
    """Place an outbound call with AMD enabled. Returns {callid, status}."""
    key = integ.get("telnyx_api_key") or os.environ.get("TELNYX_API_KEY", "")
    conn = integ.get("telnyx_connection_id", "")
    frm = integ.get("telnyx_phone_number", "")
    if not (key and conn and frm):
        raise ValueError("Telnyx is not fully configured (need API key, Connection ID and phone number).")
    payload = {
        "connection_id": conn, "to": destination, "from": frm,
        "webhook_url": f"{public_base_url()}/api/telephony/telnyx/webhook/{call_id}",
        "webhook_url_method": "POST",
        "answering_machine_detection": "detect",
        "client_state": base64.b64encode(json.dumps({"call_id": call_id}).encode()).decode(),
        "command_id": str(uuid.uuid4()),
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{TELNYX}/calls", headers=_headers(key), json=payload)
    if r.status_code >= 400:
        raise ValueError(f"Telnyx dial failed ({r.status_code}): {r.text[:200]}")
    data = r.json().get("data", {})
    return {"callid": data.get("call_control_id"), "call_leg_id": data.get("call_leg_id"), "status": "Initiated"}


async def telnyx_command(api_key: str, ccid: str, action: str, payload: dict):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{TELNYX}/calls/{ccid}/actions/{action}", headers=_headers(api_key), json=payload)
    if r.status_code >= 400:
        logger.error(f"telnyx {action} failed {r.status_code}: {r.text[:160]}")
    return r


async def telnyx_hangup(integ: dict, ccid: str):
    key = integ.get("telnyx_api_key") or os.environ.get("TELNYX_API_KEY", "")
    return await telnyx_command(key, ccid, "hangup", {"command_id": str(uuid.uuid4())})


def validate_telnyx_signature(raw: bytes, headers, public_key: str, max_age: int = 600) -> bool:
    """Ed25519 verification of `timestamp|raw_body` against the account public key.
    Fail-open only when no public key is configured (preview/demo), matching Twilio behaviour."""
    if not public_key:
        return True
    ts = headers.get("telnyx-timestamp") or headers.get("Telnyx-Timestamp")
    sig = headers.get("telnyx-signature-ed25519") or headers.get("Telnyx-Signature-Ed25519")
    if not ts or not sig:
        return False
    try:
        from nacl.signing import VerifyKey
        if abs(time.time() - int(ts)) > max_age:
            return False
        vk = VerifyKey(base64.b64decode(public_key.strip()))
        vk.verify(f"{ts}|".encode() + raw, base64.b64decode(sig.split(",")[-1].strip()))
        return True
    except Exception as e:
        logger.warning(f"telnyx signature verify failed: {e}")
        return False


async def _start_media_stream(integ: dict, ccid: str, call_id: str):
    key = integ.get("telnyx_api_key") or os.environ.get("TELNYX_API_KEY", "")
    ws_base = public_base_url().replace("https://", "wss://").replace("http://", "ws://")
    await telnyx_command(key, ccid, "streaming_start", {
        "stream_url": f"{ws_base}/api/telephony/telnyx/media/{call_id}",
        "stream_track": "both_tracks", "stream_bidirectional_mode": "rtp",
        "stream_bidirectional_codec": "PCMU", "stream_bidirectional_sampling_rate": 8000,
        "stream_bidirectional_target_legs": "opposite", "command_id": str(uuid.uuid4())})


def build_telnyx_voice_router() -> APIRouter:
    router = APIRouter(prefix="/api/telephony/telnyx", tags=["telnyx"])

    @router.post("/webhook/{call_id}")
    async def telnyx_webhook(call_id: str, request: Request):
        raw = await request.body()
        call = await db.calls.find_one({"id": call_id}, {"_id": 0})
        org = await db.organizations.find_one({"id": call["org_id"]}, {"_id": 0}) if call else None
        integ = (org or {}).get("integrations", {})
        if not validate_telnyx_signature(raw, request.headers, integ.get("telnyx_public_key", "")):
            return Response(status_code=403)
        try:
            event = json.loads(raw)
        except Exception:
            return Response(status_code=204)
        data = event.get("data", {})
        etype = data.get("event_type")
        payload = data.get("payload", {})
        ccid = payload.get("call_control_id")
        if not call:
            return Response(status_code=204)

        if etype == "call.answered":
            await db.calls.update_one({"id": call_id}, {"$set": {
                "status": "in_progress", "provider_call_sid": ccid, "answered_at": _now()}})
            await _start_media_stream(integ, ccid, call_id)
        elif etype == "call.machine.detection.ended":
            result = (payload.get("result") or "").lower()
            is_machine = telnyx_is_machine(result)
            await db.calls.update_one({"id": call_id}, {"$set": {"answered_by": result}})
            if is_machine:
                # Voicemail / answering machine — do NOT run the AI pipeline; tag + hang up.
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "voicemail": True, "outcome": "voicemail", "status": "no_answer", "ended_by": "voicemail"}})
                await telnyx_hangup(integ, ccid)
        elif etype == "call.hangup":
            cause = payload.get("hangup_cause", "")
            cur = await db.calls.find_one({"id": call_id}, {"_id": 0, "status": 1, "analysis": 1})
            if cur and cur.get("status") not in ("completed", "no_answer") and not cur.get("analysis"):
                await db.calls.update_one({"id": call_id}, {"$set": {
                    "status": "no_answer", "outcome": "no_answer",
                    "ended_by": cur.get("ended_by") or "no_answer", "hangup_cause": cause}})
        return Response(status_code=200)

    return router
