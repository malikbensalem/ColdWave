import io
import uuid
import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database import db

logger = logging.getLogger("coldwave.kb")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class KBEntryCreate(BaseModel):
    title: str
    content: str


class KBEntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


async def get_kb_entries(org_id: str, active_only: bool = False):
    q = {"org_id": org_id}
    if active_only:
        q["active"] = True
    return await db.kb_entries.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


def build_kb_router(get_current_user, record_audit):
    router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

    @router.get("")
    async def list_kb(user: dict = Depends(get_current_user)):
        return await get_kb_entries(user["org_id"])

    @router.post("")
    async def create_kb(req: KBEntryCreate, user: dict = Depends(get_current_user)):
        doc = {"id": f"kb_{uuid.uuid4().hex[:16]}", "org_id": user["org_id"], "title": req.title,
               "content": req.content, "source": "manual", "active": True, "created_at": now_iso()}
        await db.kb_entries.insert_one(dict(doc))
        await record_audit(user["org_id"], user["email"], "kb_create", "kb_entry", doc["id"],
                           after={"title": req.title})
        doc.pop("_id", None)
        return doc

    @router.put("/{kb_id}")
    async def edit_kb(kb_id: str, req: KBEntryUpdate, user: dict = Depends(get_current_user)):
        entry = await db.kb_entries.find_one({"id": kb_id, "org_id": user["org_id"]}, {"_id": 0})
        if not entry:
            raise HTTPException(404, "Entry not found")
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        if not updates:
            return entry
        await db.kb_entries.update_one({"id": kb_id, "org_id": user["org_id"]}, {"$set": updates})
        await record_audit(user["org_id"], user["email"], "kb_edit", "kb_entry", kb_id,
                           before={"title": entry.get("title")}, after={"title": updates.get("title", entry.get("title"))})
        return await db.kb_entries.find_one({"id": kb_id, "org_id": user["org_id"]}, {"_id": 0})

    @router.put("/{kb_id}/toggle")
    async def toggle_kb(kb_id: str, user: dict = Depends(get_current_user)):
        entry = await db.kb_entries.find_one({"id": kb_id, "org_id": user["org_id"]}, {"_id": 0})
        if not entry:
            from fastapi import HTTPException
            raise HTTPException(404, "Entry not found")
        new_active = not entry.get("active", True)
        await db.kb_entries.update_one({"id": kb_id, "org_id": user["org_id"]}, {"$set": {"active": new_active}})
        await record_audit(user["org_id"], user["email"], "kb_toggle", "kb_entry", kb_id,
                           before={"active": entry.get("active", True)}, after={"active": new_active})
        return {"id": kb_id, "active": new_active}

    @router.post("/upload")
    async def upload_kb(user: dict = Depends(get_current_user), file: UploadFile = File(...)):
        name = file.filename or "document"
        raw = await file.read()
        if name.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(raw))
                content = "\n".join((p.extract_text() or "") for p in reader.pages)
            except Exception as e:
                raise HTTPException(400, f"Could not parse PDF: {e}")
        elif name.lower().endswith((".txt", ".md")):
            content = raw.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(400, "Only .pdf, .txt, .md files are supported.")
        if not content.strip():
            raise HTTPException(400, "No extractable text found in file.")
        doc = {"id": f"kb_{uuid.uuid4().hex[:16]}", "org_id": user["org_id"], "title": name,
               "content": content[:20000], "source": "upload", "active": True, "created_at": now_iso()}
        await db.kb_entries.insert_one(dict(doc))
        await record_audit(user["org_id"], user["email"], "kb_upload", "kb_entry", doc["id"],
                           after={"title": name, "chars": len(content)})
        doc.pop("_id", None)
        return doc

    @router.delete("/{kb_id}")
    async def delete_kb(kb_id: str, user: dict = Depends(get_current_user)):
        before = await db.kb_entries.find_one({"id": kb_id, "org_id": user["org_id"]}, {"_id": 0})
        await db.kb_entries.delete_one({"id": kb_id, "org_id": user["org_id"]})
        await record_audit(user["org_id"], user["email"], "kb_delete", "kb_entry", kb_id,
                           before={"title": (before or {}).get("title")})
        return {"ok": True}

    return router
