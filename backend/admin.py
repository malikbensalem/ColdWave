import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from database import db
from models import BlueprintCreate, BlueprintUpdate, AssignBlueprintRequest, now_utc, new_id

logger = logging.getLogger("coldwave.admin")


async def _set_default(bid: str):
    await db.ai_blueprints.update_many({}, {"$set": {"is_default": False}})
    await db.ai_blueprints.update_one({"id": bid}, {"$set": {"is_default": True}})


async def seed_blueprints():
    if await db.ai_blueprints.find_one({"is_default": True}):
        return
    if await db.ai_blueprints.count_documents({}) == 0:
        await db.ai_blueprints.insert_one({
            "id": "bp_default", "name": "Default Blueprint",
            "prompt": ("You are a professional, compliant UK B2B outbound agent. Always be polite and concise, "
                       "never make misleading, medical, or financial guarantees, and always honour opt-out, "
                       "UK cold-calling (TPS/CTPS) and GDPR requirements."),
            "is_default": True, "created_at": now_utc().isoformat(),
        })


def build_admin_router(get_current_user, require_owner, record_audit):
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/businesses")
    async def list_businesses(user: dict = Depends(require_owner), search: str = Query(None)):
        q = {}
        if search:
            q["name"] = {"$regex": search, "$options": "i"}
        orgs = await db.organizations.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
        bps = await db.ai_blueprints.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        bpmap = {b["id"]: b["name"] for b in bps}
        out = []
        for o in orgs:
            out.append({
                "id": o["id"], "name": o["name"], "created_at": o.get("created_at"),
                "blueprint_id": o.get("blueprint_id"),
                "blueprint_name": bpmap.get(o.get("blueprint_id"), ""),
                "users": await db.users.count_documents({"org_id": o["id"]}),
                "contacts": await db.contacts.count_documents({"org_id": o["id"]}),
                "campaigns": await db.campaigns.count_documents({"org_id": o["id"]}),
                "calls": await db.calls.count_documents({"org_id": o["id"]}),
            })
        return out

    @router.get("/users")
    async def list_all_users(user: dict = Depends(require_owner), search: str = Query(None),
                             role: str = Query(None), org_id: str = Query(None)):
        q = {}
        if org_id:
            q["org_id"] = org_id
        if role:
            q["role"] = role
        if search:
            q["$or"] = [{"name": {"$regex": search, "$options": "i"}}, {"email": {"$regex": search, "$options": "i"}}]
        users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(2000)
        orgs = await db.organizations.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
        orgmap = {o["id"]: o["name"] for o in orgs}
        for u in users:
            u["org_name"] = orgmap.get(u["org_id"], "")
        return users

    @router.get("/blueprints")
    async def list_blueprints(user: dict = Depends(require_owner)):
        return await db.ai_blueprints.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)

    @router.post("/blueprints")
    async def create_blueprint(req: BlueprintCreate, user: dict = Depends(require_owner)):
        doc = {"id": new_id("bp"), "name": req.name, "prompt": req.prompt, "channel": req.channel or "global",
               "is_default": False, "created_at": now_utc().isoformat()}
        await db.ai_blueprints.insert_one(dict(doc))
        if req.is_default:
            await _set_default(doc["id"])
            doc["is_default"] = True
        await record_audit(user["org_id"], user["email"], "blueprint_create", "blueprint", doc["id"], after={"name": req.name})
        doc.pop("_id", None)
        return doc

    @router.put("/blueprints/{bid}")
    async def update_blueprint(bid: str, req: BlueprintUpdate, user: dict = Depends(require_owner)):
        bp = await db.ai_blueprints.find_one({"id": bid}, {"_id": 0})
        if not bp:
            raise HTTPException(404, "Blueprint not found")
        updates = {k: v for k, v in req.model_dump().items() if v is not None and k != "is_default"}
        if updates:
            await db.ai_blueprints.update_one({"id": bid}, {"$set": updates})
        if req.is_default:
            await _set_default(bid)
        await record_audit(user["org_id"], user["email"], "blueprint_update", "blueprint", bid)
        return await db.ai_blueprints.find_one({"id": bid}, {"_id": 0})

    @router.delete("/blueprints/{bid}")
    async def delete_blueprint(bid: str, user: dict = Depends(require_owner)):
        bp = await db.ai_blueprints.find_one({"id": bid}, {"_id": 0})
        if not bp:
            raise HTTPException(404, "Blueprint not found")
        if bp.get("is_default"):
            raise HTTPException(400, "Cannot delete the default blueprint. Set another as default first.")
        await db.ai_blueprints.delete_one({"id": bid})
        await db.organizations.update_many({"blueprint_id": bid}, {"$set": {"blueprint_id": None}})
        await record_audit(user["org_id"], user["email"], "blueprint_delete", "blueprint", bid)
        return {"ok": True}

    @router.put("/businesses/{oid}/blueprint")
    async def assign_blueprint(oid: str, req: AssignBlueprintRequest, user: dict = Depends(require_owner)):
        org = await db.organizations.find_one({"id": oid}, {"_id": 0})
        if not org:
            raise HTTPException(404, "Business not found")
        if req.blueprint_id and not await db.ai_blueprints.find_one({"id": req.blueprint_id}):
            raise HTTPException(404, "Blueprint not found")
        await db.organizations.update_one({"id": oid}, {"$set": {"blueprint_id": req.blueprint_id}})
        await record_audit(user["org_id"], user["email"], "blueprint_assign", "organization", oid,
                           after={"blueprint_id": req.blueprint_id})
        return {"ok": True, "blueprint_id": req.blueprint_id}

    return router
