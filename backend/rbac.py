import logging
from fastapi import APIRouter, Depends, HTTPException
from database import db
from models import RoleCreate, RoleUpdate, now_utc, new_id
from permissions import SYSTEMS, CAPABILITIES, BUILTIN_ROLES, _normalise

logger = logging.getLogger("coldwave.rbac")

RESERVED = {"owner", "admin", "agent"}


def build_rbac_router(get_current_user, user_can, user_has_cap, record_audit):
    router = APIRouter(prefix="/api", tags=["rbac"])

    @router.get("/systems")
    async def list_systems(user: dict = Depends(get_current_user)):
        return {"systems": SYSTEMS, "capabilities": CAPABILITIES}

    @router.get("/roles")
    async def list_roles(user: dict = Depends(get_current_user)):
        is_owner = user.get("role") == "owner"
        out = []
        # Built-in roles
        for name, r in BUILTIN_ROLES.items():
            if name == "owner" and not is_owner:
                continue
            out.append({"name": r["name"], "is_system": True, "scope": "platform",
                        "permissions": _normalise(r["permissions"]), "capabilities": list(r["capabilities"]),
                        "editable": False})
        # Platform custom roles (visible everywhere)
        plat = await db.roles.find({"scope": "platform"}, {"_id": 0}).to_list(500)
        for r in plat:
            out.append({**r, "permissions": _normalise(r.get("permissions", {})), "editable": is_owner})
        # Business-specific custom roles
        org_roles = await db.roles.find({"scope": user["org_id"]}, {"_id": 0}).to_list(500)
        for r in org_roles:
            out.append({**r, "permissions": _normalise(r.get("permissions", {})), "editable": True})
        return out

    @router.post("/roles")
    async def create_role(req: RoleCreate, user: dict = Depends(get_current_user)):
        if not await user_has_cap(user, "grant_privileges") and user.get("role") != "owner":
            raise HTTPException(403, "You don't have permission to manage roles.")
        name = req.name.strip().lower().replace(" ", "_")
        if not name or name in RESERVED:
            raise HTTPException(400, "Invalid or reserved role name.")
        is_owner = user.get("role") == "owner"
        scope = req.scope if (is_owner and req.scope) else user["org_id"]
        if await db.roles.find_one({"name": name, "scope": scope}):
            raise HTTPException(400, "A role with that name already exists in this scope.")
        # Non-owners can only grant capabilities they themselves hold.
        caps = list(req.capabilities or [])
        if not is_owner:
            from permissions import resolve_permissions
            mine = (await resolve_permissions(db, user))["capabilities"]
            caps = [c for c in caps if c in mine]
        doc = {"id": new_id("role"), "name": name, "scope": scope, "is_system": False,
               "permissions": _normalise(req.permissions), "capabilities": caps,
               "created_by": user["email"], "created_at": now_utc().isoformat()}
        await db.roles.insert_one(dict(doc))
        await record_audit(user["org_id"], user["email"], "role_create", "role", doc["id"], after={"name": name, "scope": scope})
        doc.pop("_id", None)
        return doc

    @router.put("/roles/{role_id}")
    async def update_role(role_id: str, req: RoleUpdate, user: dict = Depends(get_current_user)):
        if not await user_has_cap(user, "grant_privileges") and user.get("role") != "owner":
            raise HTTPException(403, "You don't have permission to manage roles.")
        role = await db.roles.find_one({"id": role_id}, {"_id": 0})
        if not role:
            raise HTTPException(404, "Role not found")
        if role["scope"] != user["org_id"] and user.get("role") != "owner":
            raise HTTPException(403, "You can only edit roles in your own business.")
        updates = {}
        if req.permissions is not None:
            updates["permissions"] = _normalise(req.permissions)
        if req.capabilities is not None:
            caps = list(req.capabilities)
            if user.get("role") != "owner":
                from permissions import resolve_permissions
                mine = (await resolve_permissions(db, user))["capabilities"]
                caps = [c for c in caps if c in mine]
            updates["capabilities"] = caps
        if req.name is not None:
            nn = req.name.strip().lower().replace(" ", "_")
            if nn in RESERVED:
                raise HTTPException(400, "Reserved role name.")
            updates["name"] = nn
        await db.roles.update_one({"id": role_id}, {"$set": updates})
        await record_audit(user["org_id"], user["email"], "role_update", "role", role_id, after=list(updates.keys()))
        return await db.roles.find_one({"id": role_id}, {"_id": 0})

    @router.delete("/roles/{role_id}")
    async def delete_role(role_id: str, user: dict = Depends(get_current_user)):
        if not await user_has_cap(user, "grant_privileges") and user.get("role") != "owner":
            raise HTTPException(403, "You don't have permission to manage roles.")
        role = await db.roles.find_one({"id": role_id}, {"_id": 0})
        if not role:
            raise HTTPException(404, "Role not found")
        if role["scope"] != user["org_id"] and user.get("role") != "owner":
            raise HTTPException(403, "You can only delete roles in your own business.")
        in_use = await db.users.count_documents({"role": role["name"], "org_id": role["scope"]}) if role["scope"] != "platform" else await db.users.count_documents({"role": role["name"]})
        if in_use:
            raise HTTPException(400, f"{in_use} user(s) still have this role. Reassign them first.")
        await db.roles.delete_one({"id": role_id})
        await record_audit(user["org_id"], user["email"], "role_delete", "role", role_id, before={"name": role["name"]})
        return {"ok": True}

    return router
