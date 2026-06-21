import uuid
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from database import db

logger = logging.getLogger("coldwave.audit")

# Per-request context (set by middleware) so audit calls don't need to thread `request` everywhere.
_ip_ctx: ContextVar[str] = ContextVar("audit_ip", default="unknown")
_corr_ctx: ContextVar[str] = ContextVar("audit_corr", default="-")


def set_request_context(ip: str, correlation_id: str):
    _ip_ctx.set(ip)
    _corr_ctx.set(correlation_id)


def get_correlation_id() -> str:
    return _corr_ctx.get()


async def audit_context_middleware(request: Request, call_next):
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    correlation_id = request.headers.get("x-correlation-id") or f"req_{uuid.uuid4().hex[:16]}"
    set_request_context(ip, correlation_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


def _diff(before: Optional[dict], after: Optional[dict]) -> dict:
    """Field-level before/after diff for changed keys (secrets are masked upstream)."""
    if before is None and after is None:
        return {}
    before = before or {}
    after = after or {}
    changed = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        if k in ("_id",):
            continue
        b, a = before.get(k), after.get(k)
        if b != a:
            changed[k] = {"before": b, "after": a}
    return changed


SECRET_FIELDS = {"password", "password_hash", "elevenlabs_api_key", "tcx_password",
                 "o365_client_secret", "whatsapp_access_token", "whatsapp_app_secret"}


def _mask(doc: Optional[dict]) -> Optional[dict]:
    if not isinstance(doc, dict):
        return doc
    out = {}
    for k, v in doc.items():
        if k in SECRET_FIELDS and v:
            out[k] = "***redacted***"
        else:
            out[k] = v
    return out


async def record_audit(org_id: str, actor: str, action: str, entity: str,
                       entity_id: str = "", before: dict = None, after: dict = None,
                       detail: str = ""):
    """Append-only audit entry. Always carries source IP + UTC timestamp + correlation id."""
    doc = {
        "id": f"log_{uuid.uuid4().hex[:16]}",
        "org_id": org_id,
        "actor": actor or "system",
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "diff": _diff(_mask(before), _mask(after)),
        "detail": detail,
        "ip": _ip_ctx.get(),
        "correlation_id": _corr_ctx.get(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.audit_logs.insert_one(dict(doc))
    logger.info(f"AUDIT org={org_id} actor={actor} action={action} entity={entity}:{entity_id} ip={doc['ip']} corr={doc['correlation_id']}")
    return doc


def build_audit_router(get_current_user, require_admin):
    router = APIRouter(prefix="/api/audit", tags=["audit"])

    @router.get("")
    async def list_audit(
        user: dict = Depends(require_admin),
        actor: str = Query(None),
        entity: str = Query(None),
        action: str = Query(None),
        date_from: str = Query(None),
        date_to: str = Query(None),
        limit: int = Query(200, le=1000),
    ):
        q = {"org_id": user["org_id"]}
        if actor:
            q["actor"] = {"$regex": actor, "$options": "i"}
        if entity:
            q["entity"] = entity
        if action:
            q["action"] = action
        if date_from or date_to:
            rng = {}
            if date_from:
                rng["$gte"] = date_from
            if date_to:
                rng["$lte"] = date_to
            q["created_at"] = rng
        return await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)

    return router
