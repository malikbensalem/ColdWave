import logging
from fastapi import APIRouter, Depends, Query
from database import db
from models import GlobalSettingsUpdate

logger = logging.getLogger("coldwave.admin")


def build_admin_router(get_current_user, require_owner, record_audit):
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/businesses")
    async def list_businesses(user: dict = Depends(require_owner)):
        orgs = await db.organizations.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
        out = []
        for o in orgs:
            out.append({
                "id": o["id"],
                "name": o["name"],
                "created_at": o.get("created_at"),
                "users": await db.users.count_documents({"org_id": o["id"]}),
                "contacts": await db.contacts.count_documents({"org_id": o["id"]}),
                "campaigns": await db.campaigns.count_documents({"org_id": o["id"]}),
                "calls": await db.calls.count_documents({"org_id": o["id"]}),
            })
        return out

    @router.get("/users")
    async def list_all_users(user: dict = Depends(require_owner), org_id: str = Query(None)):
        q = {}
        if org_id:
            q["org_id"] = org_id
        users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(2000)
        orgs = await db.organizations.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
        orgmap = {o["id"]: o["name"] for o in orgs}
        for u in users:
            u["org_name"] = orgmap.get(u["org_id"], "")
        return users

    @router.get("/global-settings")
    async def get_global_settings(user: dict = Depends(require_owner)):
        s = await db.platform_settings.find_one({"id": "platform"}, {"_id": 0})
        return s or {"id": "platform", "ai_system_prompt": ""}

    @router.put("/global-settings")
    async def update_global_settings(req: GlobalSettingsUpdate, user: dict = Depends(require_owner)):
        await db.platform_settings.update_one(
            {"id": "platform"},
            {"$set": {"id": "platform", "ai_system_prompt": req.ai_system_prompt}},
            upsert=True,
        )
        await record_audit(user["org_id"], user["email"], "global_settings_update",
                           "platform", "platform", after={"chars": len(req.ai_system_prompt)})
        return {"id": "platform", "ai_system_prompt": req.ai_system_prompt}

    return router
