import os
import jwt
import bcrypt
import uuid
import secrets
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from database import db
from models import RegisterRequest, LoginRequest, ImpersonateRequest, now_utc, new_id

JWT_ALGORITHM = "HS256"
ACCESS_MIN = 60 * 24  # 1 day
SESSION_DAYS = 7
EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, impersonator: dict = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MIN),
        "type": "access",
    }
    if impersonator:
        payload["imp"] = impersonator
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookie(response: Response, name: str, value: str, max_age: int):
    response.set_cookie(
        key=name, value=value, httponly=True, secure=True,
        samesite="none", max_age=max_age, path="/",
    )


async def _public_user(user: dict) -> dict:
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role", "agent"),
        "org_id": user["org_id"],
        "org_name": org["name"] if org else "",
        "auth_provider": user.get("auth_provider", "password"),
        "picture": user.get("picture", ""),
        "impersonating": bool(user.get("_impersonator")),
        "impersonator": user.get("_impersonator") or None,
    }


async def _user_from_session_token(token: str):
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        return None
    expires_at = sess["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return await db.users.find_one({"id": sess["user_id"]}, {"_id": 0})


async def get_current_user(request: Request) -> dict:
    bearer = ""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer = auth_header[7:]

    # Google/Emergent session token (cookie or bearer)
    for st in (request.cookies.get("session_token"), bearer):
        if st:
            u = await _user_from_session_token(st)
            if u:
                return u

    # JWT access token (cookie or bearer)
    token = request.cookies.get("access_token") or bearer
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if payload.get("imp"):
            user["_impersonator"] = payload["imp"]
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_owner(user: dict = Depends(get_current_user)) -> dict:
    # The real actor must be an owner (impersonation does not grant owner powers).
    real_role = user.get("_impersonator", {}).get("role") if user.get("_impersonator") else user.get("role")
    if real_role != "owner":
        raise HTTPException(status_code=403, detail="Platform owner access required")
    return user


async def _create_org(name: str) -> dict:
    org = {
        "id": new_id("org"),
        "name": name,
        "calling_hours_start": "08:00",
        "calling_hours_end": "20:00",
        "calling_days": ["mon", "tue", "wed", "thu", "fri"],
        "opening_mode": "scripted",
        "opening_creativity": "medium",
        "opening_max_length": 220,
        "integrations": {
            "tcx_enabled": False, "tcx_url": "", "tcx_username": "", "tcx_password": "",
            "tcx_extension": "", "elevenlabs_api_key": "", "elevenlabs_enabled": False,
            "o365_enabled": False, "o365_tenant_id": "", "o365_client_id": "",
            "o365_client_secret": "", "llm_provider": "anthropic", "llm_model": "claude-sonnet-4-6",
        },
        "created_at": now_utc().isoformat(),
    }
    await db.organizations.insert_one(dict(org))
    return org


@auth_router.post("/register")
async def register(req: RegisterRequest, response: Response):
    email = req.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    org = await _create_org(req.org_name)
    user = {
        "id": new_id("user"),
        "org_id": org["id"],
        "email": email,
        "name": req.name,
        "password_hash": hash_password(req.password),
        "role": "admin",
        "auth_provider": "password",
        "picture": "",
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(dict(user))
    token = create_access_token(user["id"], email)
    set_auth_cookie(response, "access_token", token, ACCESS_MIN * 60)
    out = await _public_user(user)
    out["access_token"] = token
    return out


@auth_router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.lower()
    ip = request.client.host if request.client else "unknown"
    identifier = f"{ip}:{email}"
    attempt = await db.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("count", 0) >= 5:
        locked_until = attempt.get("locked_until")
        if locked_until and datetime.fromisoformat(locked_until) > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(req.password, user["password_hash"]):
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1},
             "$set": {"locked_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}},
            upsert=True,
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await db.login_attempts.delete_one({"identifier": identifier})
    token = create_access_token(user["id"], email)
    set_auth_cookie(response, "access_token", token, ACCESS_MIN * 60)
    out = await _public_user(user)
    out["access_token"] = token
    return out


@auth_router.post("/google/session")
async def google_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    async with httpx.AsyncClient(timeout=15) as cx:
        r = await cx.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = data["email"].lower()
    user = await db.users.find_one({"email": email})
    if not user:
        org = await _create_org(f"{data.get('name', email)}'s Workspace")
        user = {
            "id": new_id("user"),
            "org_id": org["id"],
            "email": email,
            "name": data.get("name", email),
            "password_hash": "",
            "role": "admin",
            "auth_provider": "google",
            "picture": data.get("picture", ""),
            "created_at": now_utc().isoformat(),
        }
        await db.users.insert_one(dict(user))
    else:
        await db.users.update_one({"id": user["id"]}, {"$set": {"picture": data.get("picture", "")}})

    session_token = data["session_token"]
    await db.user_sessions.insert_one({
        "user_id": user["id"],
        "session_token": session_token,
        "expires_at": (now_utc() + timedelta(days=SESSION_DAYS)).isoformat(),
        "created_at": now_utc().isoformat(),
    })
    set_auth_cookie(response, "session_token", session_token, SESSION_DAYS * 24 * 3600)
    out = await _public_user(user)
    out["access_token"] = session_token
    return out


@auth_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return await _public_user(user)


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


@auth_router.post("/impersonate")
async def impersonate(req: ImpersonateRequest, response: Response, user: dict = Depends(get_current_user)):
    if user.get("_impersonator"):
        raise HTTPException(status_code=400, detail="Already impersonating. Stop impersonation first.")
    target = await db.users.find_one({"id": req.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="You cannot impersonate yourself")
    role = user.get("role")
    if role == "owner":
        pass
    elif role == "admin":
        if target.get("org_id") != user.get("org_id") or target.get("role") == "owner":
            raise HTTPException(status_code=403, detail="You can only impersonate users within your business.")
    else:
        raise HTTPException(status_code=403, detail="You do not have permission to impersonate users.")
    imp = {"id": user["id"], "email": user["email"], "role": role,
           "org_id": user["org_id"], "name": user.get("name", "")}
    token = create_access_token(target["id"], target["email"], impersonator=imp)
    set_auth_cookie(response, "access_token", token, ACCESS_MIN * 60)
    response.delete_cookie("session_token", path="/")
    target["_impersonator"] = imp
    out = await _public_user(target)
    out["access_token"] = token
    return out


@auth_router.post("/stop-impersonation")
async def stop_impersonation(response: Response, user: dict = Depends(get_current_user)):
    imp = user.get("_impersonator")
    if not imp:
        raise HTTPException(status_code=400, detail="Not currently impersonating")
    real = await db.users.find_one({"id": imp["id"]}, {"_id": 0})
    if not real:
        raise HTTPException(status_code=404, detail="Original user not found")
    token = create_access_token(real["id"], real["email"])
    set_auth_cookie(response, "access_token", token, ACCESS_MIN * 60)
    out = await _public_user(real)
    out["access_token"] = token
    return out


async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@coldwave.ai").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin123!")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        org = await db.organizations.find_one({"name": "ColdWave Demo Co"})
        if not org:
            org = await _create_org("ColdWave Demo Co")
        await db.users.insert_one({
            "id": new_id("user"),
            "org_id": org["id"],
            "email": admin_email,
            "name": "Platform Admin",
            "password_hash": hash_password(admin_password),
            "role": "admin",
            "auth_provider": "password",
            "picture": "",
            "created_at": now_utc().isoformat(),
        })
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one(
            {"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}}
        )


async def seed_owner():
    owner_email = os.environ.get("OWNER_EMAIL", "owner@coldwave.ai").lower()
    owner_password = os.environ.get("OWNER_PASSWORD", "Owner123!")
    existing = await db.users.find_one({"email": owner_email})
    if existing is None:
        org = await db.organizations.find_one({"name": "ColdWave Platform"})
        if not org:
            org = await _create_org("ColdWave Platform")
        await db.users.insert_one({
            "id": new_id("user"),
            "org_id": org["id"],
            "email": owner_email,
            "name": "Platform Owner",
            "password_hash": hash_password(owner_password),
            "role": "owner",
            "auth_provider": "password",
            "picture": "",
            "created_at": now_utc().isoformat(),
        })
    else:
        updates = {"role": "owner"}
        if not verify_password(owner_password, existing.get("password_hash", "")):
            updates["password_hash"] = hash_password(owner_password)
        await db.users.update_one({"email": owner_email}, {"$set": updates})
