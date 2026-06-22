"""Role-based access control: governed systems, built-in role templates, and resolution."""

# Systems (resources) whose CRUD access can be governed by a role.
SYSTEMS = [
    "dashboard", "leads", "campaigns", "scripts", "voices", "email_campaigns",
    "test_calls", "whatsapp", "compliance", "integrations", "users", "roles",
    "audit", "platform_admin", "blueprints",
]

# Capability flags (non-CRUD privileges).
CAPABILITIES = [
    "view_all_businesses",   # see every business (owner)
    "impersonate_users",     # impersonate a specific user / role
    "impersonate_any_business",  # impersonate across businesses (owner)
    "manage_blueprints",     # create/assign AI blueprints (owner)
    "ban_users",             # ban / unban users
    "grant_privileges",      # create/edit roles & grant capabilities
]


def _crud(c, r, u, d):
    return {"create": c, "read": r, "update": u, "delete": d}


FULL = _crud(True, True, True, True)
READ = _crud(False, True, False, False)
NONE = _crud(False, False, False, False)


def _perms(default, **overrides):
    p = {s: dict(default) for s in SYSTEMS}
    for k, v in overrides.items():
        p[k] = dict(v)
    return p


BUILTIN_ROLES = {
    "owner": {
        "name": "owner", "is_system": True, "scope": "platform",
        "permissions": _perms(FULL),
        "capabilities": list(CAPABILITIES),
    },
    "admin": {
        "name": "admin", "is_system": True, "scope": "platform",
        "permissions": _perms(
            FULL,
            dashboard=READ, audit=READ,
            platform_admin=NONE, blueprints=NONE,
        ),
        "capabilities": ["impersonate_users", "ban_users", "grant_privileges"],
    },
    "agent": {
        "name": "agent", "is_system": True, "scope": "platform",
        "permissions": _perms(
            NONE,
            dashboard=READ, leads=FULL, campaigns=READ, scripts=READ,
            voices=READ, test_calls=FULL, whatsapp=READ, compliance=READ,
        ),
        "capabilities": [],
    },
}


def _normalise(permissions: dict) -> dict:
    """Ensure every system key exists with a full CRUD shape."""
    out = {}
    for s in SYSTEMS:
        v = (permissions or {}).get(s) or {}
        out[s] = {
            "create": bool(v.get("create", False)),
            "read": bool(v.get("read", False)),
            "update": bool(v.get("update", False)),
            "delete": bool(v.get("delete", False)),
        }
    return out


async def resolve_role(db, role_name: str, org_id: str = None) -> dict:
    """Resolve a role definition (permissions + capabilities) for a user."""
    if role_name == "owner":
        return {**BUILTIN_ROLES["owner"], "permissions": _normalise(BUILTIN_ROLES["owner"]["permissions"])}
    # Prefer a business-specific custom role, then a platform custom role.
    doc = None
    if org_id:
        doc = await db.roles.find_one({"name": role_name, "scope": org_id}, {"_id": 0})
    if not doc:
        doc = await db.roles.find_one({"name": role_name, "scope": "platform"}, {"_id": 0})
    if doc:
        return {
            "name": doc["name"], "is_system": False, "scope": doc.get("scope", "platform"),
            "permissions": _normalise(doc.get("permissions", {})),
            "capabilities": list(doc.get("capabilities", [])),
        }
    base = BUILTIN_ROLES.get(role_name, BUILTIN_ROLES["agent"])
    return {**base, "permissions": _normalise(base["permissions"])}


async def resolve_permissions(db, user: dict) -> dict:
    role = await resolve_role(db, user.get("role", "agent"), user.get("org_id"))
    return {"permissions": role["permissions"], "capabilities": role["capabilities"]}
