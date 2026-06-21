import asyncio
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from database import db
from models import (
    EmailIntegrationUpdate, EmailCampaignCreate, EmailCampaignUpdate, now_utc, new_id,
)

logger = logging.getLogger("coldwave.email")

AUDIENCE_QUERY = {
    "all": {},
    "positive": {"status": "positive"},
    "contacted": {"status": "contacted"},
    "consented": {"consent": True},
}

_RECURRENCE_DELTA = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


async def _recipients(org_id: str, audience: str):
    q = {"org_id": org_id, "opted_out": {"$ne": True}, "email": {"$nin": ["", None]}}
    q.update(AUDIENCE_QUERY.get(audience, {}))
    return await db.contacts.find(q, {"_id": 0, "email": 1, "name": 1}).to_list(5000)


async def _mock_send(camp: dict) -> int:
    """MOCK email send — counts eligible recipients and logs. No real email is sent."""
    recips = await _recipients(camp["org_id"], camp.get("audience", "all"))
    count = len(recips)
    logger.info(f"[MOCK EMAIL] '{camp.get('name')}' via {camp.get('provider') or 'unconfigured'} "
                f"-> {count} recipients (subject='{camp.get('subject')}')")
    return count


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def email_scheduler_loop():
    """Background loop that processes due scheduled / recurring email campaigns (MOCK send)."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            due = await db.email_campaigns.find(
                {"status": "scheduled", "next_run_at": {"$lte": now.isoformat()}}, {"_id": 0}
            ).to_list(200)
            for camp in due:
                count = await _mock_send(camp)
                updates = {
                    "last_sent_at": now.isoformat(),
                    "sent_count": camp.get("sent_count", 0) + count,
                }
                if camp.get("schedule_type") == "recurring" and camp.get("recurrence"):
                    delta = _RECURRENCE_DELTA[camp["recurrence"]]
                    nxt = _parse_iso(camp["next_run_at"])
                    while nxt <= now:
                        nxt = nxt + delta
                    updates["next_run_at"] = nxt.isoformat()
                    updates["status"] = "scheduled"
                else:
                    updates["status"] = "sent"
                await db.email_campaigns.update_one({"id": camp["id"]}, {"$set": updates})
        except Exception as e:
            logger.error(f"email scheduler error: {e}")
        await asyncio.sleep(30)


def build_email_router(get_current_user, require_admin, record_audit):
    router = APIRouter(prefix="/api", tags=["email"])

    # ---- Connection (Gmail / Office 365) — MOCK connection ----
    @router.get("/email/integration")
    async def get_email_integration(user: dict = Depends(get_current_user)):
        org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
        ec = (org or {}).get("email_integration", {})
        return {"provider": ec.get("provider", ""), "account_email": ec.get("account_email", ""),
                "connected": bool(ec.get("provider"))}

    @router.put("/email/integration")
    async def connect_email(req: EmailIntegrationUpdate, user: dict = Depends(require_admin)):
        ec = {"provider": req.provider, "account_email": req.account_email,
              "connected_at": now_utc().isoformat()}
        await db.organizations.update_one({"id": user["org_id"]}, {"$set": {"email_integration": ec}})
        await record_audit(user["org_id"], user["email"], "email_connect", "integration",
                           req.provider, after={"provider": req.provider})
        return {**ec, "connected": True}

    @router.delete("/email/integration")
    async def disconnect_email(user: dict = Depends(require_admin)):
        await db.organizations.update_one({"id": user["org_id"]}, {"$unset": {"email_integration": ""}})
        await record_audit(user["org_id"], user["email"], "email_disconnect", "integration", "")
        return {"ok": True}

    @router.get("/email/recipients")
    async def recipients_preview(audience: str = Query("all"), user: dict = Depends(get_current_user)):
        recips = await _recipients(user["org_id"], audience)
        return {"count": len(recips), "sample": [r.get("email") for r in recips[:5]]}

    # ---- Campaigns ----
    @router.get("/email-campaigns")
    async def list_email_campaigns(user: dict = Depends(get_current_user)):
        return await db.email_campaigns.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)

    @router.post("/email-campaigns")
    async def create_email_campaign(req: EmailCampaignCreate, user: dict = Depends(get_current_user)):
        org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
        provider = (org or {}).get("email_integration", {}).get("provider", "")
        doc = {
            "id": new_id("ecamp"), "org_id": user["org_id"], "name": req.name,
            "subject": req.subject, "body": req.body, "schedule_type": req.schedule_type,
            "recurrence": req.recurrence, "audience": req.audience, "provider": provider,
            "sent_count": 0, "last_sent_at": None, "scheduled_at": None, "next_run_at": None,
            "status": "draft", "created_at": now_utc().isoformat(),
        }
        if req.schedule_type == "now":
            count = await _mock_send(doc)
            doc["status"] = "sent"
            doc["sent_count"] = count
            doc["last_sent_at"] = now_utc().isoformat()
        else:
            if not req.scheduled_at:
                raise HTTPException(400, "A scheduled date/time is required for scheduled or recurring campaigns.")
            doc["scheduled_at"] = req.scheduled_at
            doc["next_run_at"] = req.scheduled_at
            doc["status"] = "scheduled"
        await db.email_campaigns.insert_one(dict(doc))
        await record_audit(user["org_id"], user["email"], "email_campaign_create", "email_campaign",
                           doc["id"], after={"name": req.name, "schedule": req.schedule_type})
        doc.pop("_id", None)
        return doc

    @router.put("/email-campaigns/{cid}")
    async def update_email_campaign(cid: str, req: EmailCampaignUpdate, user: dict = Depends(get_current_user)):
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        if "scheduled_at" in updates:
            updates["next_run_at"] = updates["scheduled_at"]
        res = await db.email_campaigns.update_one({"id": cid, "org_id": user["org_id"]}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(404, "Email campaign not found")
        return await db.email_campaigns.find_one({"id": cid}, {"_id": 0})

    @router.post("/email-campaigns/{cid}/send-now")
    async def send_now(cid: str, user: dict = Depends(get_current_user)):
        camp = await db.email_campaigns.find_one({"id": cid, "org_id": user["org_id"]}, {"_id": 0})
        if not camp:
            raise HTTPException(404, "Email campaign not found")
        count = await _mock_send(camp)
        await db.email_campaigns.update_one({"id": cid}, {"$set": {
            "status": "sent", "last_sent_at": now_utc().isoformat(),
            "sent_count": camp.get("sent_count", 0) + count,
        }})
        await record_audit(user["org_id"], user["email"], "email_campaign_send", "email_campaign",
                           cid, after={"recipients": count})
        return {"ok": True, "recipients": count, "mock": True}

    @router.delete("/email-campaigns/{cid}")
    async def delete_email_campaign(cid: str, user: dict = Depends(get_current_user)):
        await db.email_campaigns.delete_one({"id": cid, "org_id": user["org_id"]})
        await record_audit(user["org_id"], user["email"], "email_campaign_delete", "email_campaign", cid)
        return {"ok": True}

    return router
