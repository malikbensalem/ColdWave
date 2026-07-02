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
from models import SimulateInboundRequest, ApprovalEditRequest, new_id
from integrations import llm_generate

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


CHANNEL_INSTRUCTIONS = {
    "whatsapp": "You are drafting a WhatsApp reply to a prospect. Keep it short, warm and professional; no markdown.",
    "sms": "You are drafting an SMS reply. Keep it under 300 characters, plain text, with a clear opt-out (reply STOP).",
    "email": "You are drafting an email reply. Use a brief professional greeting and a short sign-off.",
}


async def _channel_system_prompt(org: dict, channel: str) -> str:
    """Resolve the AI system prompt for a channel: the org's assigned channel blueprint (if any),
    else a channel-specific blueprint, else the global default; plus org AI extension + channel style."""
    bp = None
    assigned = (org or {}).get("channel_blueprints", {}).get(channel)
    if assigned:
        bp = await db.ai_blueprints.find_one({"id": assigned}, {"_id": 0})
    if not bp:
        bp = await db.ai_blueprints.find_one({"channel": channel}, {"_id": 0}, sort=[("created_at", -1)])
    if not bp:
        bp = await db.ai_blueprints.find_one({"is_default": True}, {"_id": 0})
    base = (bp or {}).get("prompt", "")
    org_ext = (org or {}).get("ai_system_prompt", "")
    parts = [p for p in [base, org_ext, CHANNEL_INSTRUCTIONS.get(channel, "")] if p]
    return "\n\n".join(parts)


async def _generate_draft(org: dict, channel: str, inbound_text: str) -> str:
    system = await _channel_system_prompt(org, channel)
    prompt = (f'A prospect sent this inbound {channel} message:\n"{inbound_text}"\n\n'
              "Write a suitable reply. Output ONLY the reply text — no preamble.")
    try:
        reply = await llm_generate(f"reply_{org.get('id','')}_{channel}", system, prompt, org)
        return (reply or "").strip()
    except Exception as e:
        logger.error(f"AI draft generation failed: {e}")
        return ""


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

    # ---- AI auto-reply + human approval queue (P2/P3) ----
    @router.post("/approvals/simulate-inbound")
    async def simulate_inbound(req: SimulateInboundRequest, user: dict = Depends(get_current_user)):
        """Test helper: record an inbound message and generate an AI draft reply awaiting human approval."""
        org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0}) or {}
        await db.messages.insert_one({
            "id": f"msg_{uuid.uuid4().hex[:16]}", "org_id": user["org_id"], "channel": req.channel,
            "from": req.sender, "contact_id": req.contact_id, "direction": "inbound", "type": "text",
            "body": req.text, "state": "received", "created_at": now_iso(), "updated_at": now_iso()})
        draft = await _generate_draft({**org, "id": user["org_id"]}, req.channel, req.text)
        ap = {
            "id": f"appr_{uuid.uuid4().hex[:16]}", "org_id": user["org_id"], "channel": req.channel,
            "sender": req.sender, "contact_id": req.contact_id, "inbound_text": req.text,
            "draft_text": draft, "state": "pending", "ai_generated": bool(draft),
            "created_at": now_iso(), "updated_at": now_iso()}
        await db.message_approvals.insert_one(dict(ap))
        await record_audit(user["org_id"], user["email"], "approval_draft", "approval", ap["id"],
                           after={"channel": req.channel, "from": mask_phone(req.sender)})
        ap.pop("_id", None)
        return ap

    @router.get("/approvals")
    async def list_approvals(user: dict = Depends(get_current_user), state: str = Query(None)):
        q = {"org_id": user["org_id"]}
        if state:
            q["state"] = state
        return await db.message_approvals.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)

    @router.put("/approvals/{aid}")
    async def edit_approval(aid: str, req: ApprovalEditRequest, user: dict = Depends(get_current_user)):
        res = await db.message_approvals.update_one(
            {"id": aid, "org_id": user["org_id"], "state": "pending"},
            {"$set": {"draft_text": req.draft_text, "edited": True, "updated_at": now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(404, "Pending approval not found")
        return await db.message_approvals.find_one({"id": aid}, {"_id": 0})

    @router.post("/approvals/{aid}/reject")
    async def reject_approval(aid: str, user: dict = Depends(get_current_user)):
        res = await db.message_approvals.update_one(
            {"id": aid, "org_id": user["org_id"], "state": "pending"},
            {"$set": {"state": "rejected", "updated_at": now_iso()}})
        if res.matched_count == 0:
            raise HTTPException(404, "Pending approval not found")
        await record_audit(user["org_id"], user["email"], "approval_reject", "approval", aid)
        return {"ok": True}

    @router.post("/approvals/{aid}/approve")
    async def approve_approval(aid: str, user: dict = Depends(get_current_user)):
        """Human approves the AI draft — only now is the reply actually sent."""
        ap = await db.message_approvals.find_one({"id": aid, "org_id": user["org_id"]}, {"_id": 0})
        if not ap:
            raise HTTPException(404, "Approval not found")
        if ap["state"] != "pending":
            raise HTTPException(400, f"Approval already {ap['state']}.")
        if not (ap.get("draft_text") or "").strip():
            raise HTTPException(400, "Draft is empty — edit it before approving.")
        dnc = await db.dnc_list.find_one({"org_id": user["org_id"], "phone": ap["sender"]})
        if dnc:
            raise HTTPException(403, "Recipient is on the Do-Not-Call list.")

        state, provider_name, is_mock, err = "sent", "", True, None
        if ap["channel"] == "whatsapp":
            org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
            provider, is_mock = get_whatsapp_provider(org)
            provider_name = provider.name
            try:
                await provider.send_text(ap["sender"], ap["draft_text"])
            except Exception as e:
                state, err = "failed", str(e)
        # sms / email: channel send is pluggable — recorded as sent (mock) until a live gateway/OAuth is wired.
        await db.messages.insert_one({
            "id": f"msg_{uuid.uuid4().hex[:16]}", "org_id": user["org_id"], "channel": ap["channel"],
            "to": ap["sender"], "contact_id": ap.get("contact_id"), "direction": "outbound", "type": "text",
            "body": ap["draft_text"], "state": "delivered" if state == "sent" else state,
            "provider": provider_name or ap["channel"], "mock": is_mock, "approved_by": user["email"],
            "created_at": now_iso(), "updated_at": now_iso()})
        await db.message_approvals.update_one({"id": aid}, {"$set": {
            "state": state, "approved_by": user["email"], "error": err, "updated_at": now_iso()}})
        await record_audit(user["org_id"], user["email"], "approval_approve", "approval", aid,
                           after={"channel": ap["channel"], "state": state})
        if state == "failed":
            raise HTTPException(502, f"Approved but send failed: {err}")
        return {"ok": True, "state": state, "mock": is_mock}

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
