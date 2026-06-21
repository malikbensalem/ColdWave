import os
import hmac
import json
import uuid
import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from database import db

logger = logging.getLogger("coldwave.messaging")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def mask_phone(phone: str) -> str:
    if not phone:
        return ""
    p = str(phone)
    return p[:4] + "***" + p[-2:] if len(p) > 6 else "***"


# ---------------- Provider abstraction ----------------
class MessagingProvider(ABC):
    name = "base"

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict:
        ...


class MockWhatsAppProvider(MessagingProvider):
    name = "whatsapp_mock"

    async def send_text(self, to: str, body: str) -> dict:
        await asyncio.sleep(0)
        return {"messages": [{"id": f"mock_wamid_{uuid.uuid4().hex[:18]}"}], "mock": True}


class WhatsAppCloudProvider(MessagingProvider):
    name = "whatsapp_cloud"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        version = cfg.get("graph_api_version") or os.environ.get("GRAPH_API_VERSION", "v23.0")
        self.url = f"https://graph.facebook.com/{version}/{cfg['phone_number_id']}/messages"
        self.token = cfg["access_token"]

    async def send_text(self, to: str, body: str) -> dict:
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                   "to": to, "type": "text", "text": {"body": body}}
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        last_err = None
        for attempt in range(3):  # retries with backoff
            try:
                async with httpx.AsyncClient(timeout=20) as cx:
                    r = await cx.post(self.url, headers=headers, json=payload)
                    r.raise_for_status()
                    return r.json()
            except Exception as e:
                last_err = e
                logger.warning(f"WhatsApp send attempt {attempt+1} failed to {mask_phone(to)}: {e}")
                await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"WhatsApp send failed after retries: {last_err}")


def _wa_config(org: dict) -> dict:
    integ = (org or {}).get("integrations", {})
    return {
        "phone_number_id": integ.get("whatsapp_phone_number_id") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        "access_token": integ.get("whatsapp_access_token") or os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
        "app_secret": integ.get("whatsapp_app_secret") or os.environ.get("WHATSAPP_APP_SECRET", ""),
        "graph_api_version": os.environ.get("GRAPH_API_VERSION", "v23.0"),
    }


def get_whatsapp_provider(org: dict):
    cfg = _wa_config(org)
    if cfg["phone_number_id"] and cfg["access_token"]:
        return WhatsAppCloudProvider(cfg), False  # (provider, is_mock)
    return MockWhatsAppProvider(), True


# ---------------- Rate limiting ----------------
async def _check_rate_limit(org_id: str):
    limit = int(os.environ.get("MESSAGE_RATE_LIMIT_PER_MIN", "30"))
    window_start = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    count = await db.messages.count_documents({
        "org_id": org_id, "direction": "outbound", "created_at": {"$gte": window_start}
    })
    if count >= limit:
        raise HTTPException(429, f"Rate limit exceeded ({limit}/min). Try again shortly.")


# ---------------- Routes ----------------
class SendMessageRequest(BaseModel):
    to: str
    body: str
    contact_id: Optional[str] = None


def build_messaging_router(get_current_user, record_audit):
    router = APIRouter(prefix="/api/messages", tags=["messaging"])

    @router.post("/whatsapp/send")
    async def send_whatsapp(req: SendMessageRequest, user: dict = Depends(get_current_user)):
        org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
        # DNC / opt-out safety check
        dnc = await db.dnc_list.find_one({"org_id": user["org_id"], "phone": req.to})
        if dnc:
            raise HTTPException(403, "Recipient is on the Do-Not-Call list.")
        await _check_rate_limit(user["org_id"])

        provider, is_mock = get_whatsapp_provider(org)
        msg = {
            "id": f"msg_{uuid.uuid4().hex[:16]}", "org_id": user["org_id"], "channel": "whatsapp",
            "provider": provider.name, "to": req.to, "contact_id": req.contact_id,
            "direction": "outbound", "type": "text", "body": req.body, "state": "queued",
            "provider_message_id": None, "error": None, "mock": is_mock,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.messages.insert_one(dict(msg))
        try:
            res = await provider.send_text(req.to, req.body)
            pmid = (res.get("messages") or [{}])[0].get("id")
            await db.messages.update_one({"id": msg["id"]}, {"$set": {
                "state": "sent", "provider_message_id": pmid, "updated_at": now_iso()}})
            msg.update({"state": "sent", "provider_message_id": pmid})
            logger.info(f"WhatsApp sent to {mask_phone(req.to)} via {provider.name} mock={is_mock} id={pmid}")
        except Exception as e:
            await db.messages.update_one({"id": msg["id"]}, {"$set": {
                "state": "failed", "error": str(e), "updated_at": now_iso()}})
            # dead-letter record
            await db.message_dead_letters.insert_one({
                "id": f"dl_{uuid.uuid4().hex[:12]}", "message_id": msg["id"], "org_id": user["org_id"],
                "to": mask_phone(req.to), "error": str(e), "created_at": now_iso()})
            msg.update({"state": "failed", "error": str(e)})
            logger.error(f"WhatsApp send FAILED to {mask_phone(req.to)}: {e}")

        await record_audit(user["org_id"], user["email"], "message_send", "message", msg["id"],
                           after={"to": mask_phone(req.to), "channel": "whatsapp", "state": msg["state"]})
        if is_mock and msg["state"] == "sent":
            # simulate delivery progression for local/test visibility
            await db.messages.update_one({"id": msg["id"]}, {"$set": {"state": "delivered", "updated_at": now_iso()}})
            msg["state"] = "delivered"
        return {k: msg[k] for k in ("id", "state", "provider_message_id", "mock", "to")}

    @router.get("")
    async def list_messages(user: dict = Depends(get_current_user),
                            state: str = Query(None), direction: str = Query(None),
                            contact_id: str = Query(None)):
        q = {"org_id": user["org_id"]}
        if state:
            q["state"] = state
        if direction:
            q["direction"] = direction
        if contact_id:
            q["contact_id"] = contact_id
        return await db.messages.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)

    @router.get("/dead-letters")
    async def list_dead_letters(user: dict = Depends(get_current_user)):
        return await db.message_dead_letters.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)

    return router


# ---------------- Webhook (Meta WhatsApp Cloud) ----------------
def build_whatsapp_webhook_router():
    router = APIRouter(prefix="/api/webhooks/whatsapp", tags=["whatsapp-webhook"])

    @router.get("")
    async def verify(hub_mode: str = Query(None, alias="hub.mode"),
                     hub_challenge: str = Query(None, alias="hub.challenge"),
                     hub_verify_token: str = Query(None, alias="hub.verify_token")):
        expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
        if hub_mode == "subscribe" and expected and hub_verify_token == expected:
            return PlainTextResponse(hub_challenge or "")
        raise HTTPException(403, "Webhook verification failed")

    @router.post("")
    async def inbound(request: Request):
        raw = await request.body()
        sig = request.headers.get("X-Hub-Signature-256", "")
        app_secret = os.environ.get("WHATSAPP_APP_SECRET", "")
        # Signature verification (skipped only when no app secret configured = sandbox/mock).
        if app_secret:
            if not sig.startswith("sha256="):
                raise HTTPException(401, "Missing signature")
            expected = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig.split("=", 1)[1]):
                raise HTTPException(401, "Invalid signature")
        try:
            payload = json.loads(raw)
        except Exception:
            raise HTTPException(400, "Invalid payload")

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # inbound messages
                for m in value.get("messages", []):
                    frm = m.get("from", "")
                    body = (m.get("text") or {}).get("body", "")
                    await db.messages.insert_one({
                        "id": f"msg_{uuid.uuid4().hex[:16]}", "org_id": "inbound",
                        "channel": "whatsapp", "provider": "whatsapp_cloud", "from": frm,
                        "direction": "inbound", "type": m.get("type", "text"), "body": body,
                        "state": "received", "provider_message_id": m.get("id"),
                        "created_at": now_iso(), "updated_at": now_iso()})
                    logger.info(f"WhatsApp inbound from {mask_phone(frm)} id={m.get('id')}")
                # delivery status updates
                for st in value.get("statuses", []):
                    status_map = {"sent": "sent", "delivered": "delivered", "read": "delivered", "failed": "failed"}
                    new_state = status_map.get(st.get("status"), st.get("status"))
                    await db.messages.update_one(
                        {"provider_message_id": st.get("id")},
                        {"$set": {"state": new_state, "updated_at": now_iso()}})
        return {"ok": True}

    return router


async def create_messaging_indexes():
    await db.messages.create_index([("org_id", 1), ("created_at", -1)])
    await db.messages.create_index("provider_message_id")
    await db.message_dead_letters.create_index([("org_id", 1), ("created_at", -1)])
