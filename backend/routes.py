import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from database import db
from auth import get_current_user, require_admin, hash_password
from models import (
    ContactCreate, ContactUpdate, ScriptCreate, ScriptUpdate, GenerateScriptRequest,
    CampaignCreate, CampaignUpdate, VoicePreviewRequest, TestCallStartRequest,
    TestCallTurnRequest, DNCAddRequest, ErasureRequest, OrgUpdateRequest,
    IntegrationSettings, InviteUserRequest, UpdateUserRequest, ElevenLabsTestRequest,
    LLMTestRequest, now_utc, new_id,
)
from integrations import (
    VOICE_CATALOG, get_voice, generate_voice_preview, generate_script,
    agent_reply, analyze_transcript, generate_tts, select_tts_provider,
    validate_elevenlabs_key, generate_kb_opening, get_llm_models, validate_llm_key, llm_config,
)
from audit import record_audit
from kb import get_kb_entries

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["app"])

PIPELINE_STATUSES = ["new", "contacted", "positive", "callback", "opted_out", "dnc"]


async def audit(org_id: str, user: dict, action: str, detail: str = "", entity: str = "system",
                entity_id: str = "", before: dict = None, after: dict = None):
    await record_audit(org_id, user.get("email", "system"), action, entity, entity_id,
                       before=before, after=after, detail=detail)


def clean(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# ---------------- Dashboard ----------------
@router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    contacts = await db.contacts.find({"org_id": org_id}, {"_id": 0}).to_list(5000)
    calls = await db.calls.find({"org_id": org_id}, {"_id": 0}).to_list(5000)
    by_status = {s: 0 for s in PIPELINE_STATUSES}
    for c in contacts:
        by_status[c.get("status", "new")] = by_status.get(c.get("status", "new"), 0) + 1
    connected = [c for c in calls if c.get("status") == "completed"]
    positive = [c for c in calls if c.get("sentiment") == "positive"]
    opt_outs = [c for c in calls if c.get("opted_out")]
    campaigns = await db.campaigns.count_documents({"org_id": org_id})
    recent = sorted(calls, key=lambda x: x.get("created_at", ""), reverse=True)[:8]
    # call volume last 7 days
    from collections import defaultdict
    vol = defaultdict(int)
    for c in calls:
        day = (c.get("created_at", "") or "")[:10]
        if day:
            vol[day] += 1
    timeline = sorted([{"date": k, "calls": v} for k, v in vol.items()], key=lambda x: x["date"])[-7:]
    return {
        "total_contacts": len(contacts),
        "total_calls": len(calls),
        "connect_rate": round(len(connected) / len(calls) * 100) if calls else 0,
        "positive_responses": len(positive),
        "opt_outs": len(opt_outs),
        "active_campaigns": campaigns,
        "by_status": by_status,
        "recent_calls": recent,
        "timeline": timeline,
        "sentiment_breakdown": {
            "positive": len(positive),
            "neutral": len([c for c in calls if c.get("sentiment") == "neutral"]),
            "negative": len([c for c in calls if c.get("sentiment") == "negative"]),
        },
    }


# ---------------- Contacts (CRM) ----------------
@router.get("/contacts")
async def list_contacts(user: dict = Depends(get_current_user), status: str = Query(None), search: str = Query(None)):
    q = {"org_id": user["org_id"]}
    if status:
        q["status"] = status
    if search:
        q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    return await db.contacts.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.post("/contacts")
async def create_contact(req: ContactCreate, user: dict = Depends(get_current_user)):
    dnc = await db.dnc_list.find_one({"org_id": user["org_id"], "phone": req.phone})
    doc = {
        "id": new_id("contact"), "org_id": user["org_id"], "name": req.name, "phone": req.phone,
        "email": req.email or "", "company": req.company or "", "notes": req.notes or "",
        "consent": req.consent, "status": "dnc" if dnc else "new", "opted_out": bool(dnc),
        "sentiment": None, "last_called_at": None, "created_at": now_utc().isoformat(),
    }
    await db.contacts.insert_one(dict(doc))
    await audit(user["org_id"], user, "create", entity="contact", entity_id=doc["id"], after=doc)
    return clean(doc)


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: str, user: dict = Depends(get_current_user)):
    c = await db.contacts.find_one({"id": contact_id, "org_id": user["org_id"]}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contact not found")
    c["calls"] = await db.calls.find({"contact_id": contact_id, "org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return c


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, req: ContactUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No updates provided")
    res = await db.contacts.update_one({"id": contact_id, "org_id": user["org_id"]}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Contact not found")
    after = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    await audit(user["org_id"], user, "update", entity="contact", entity_id=contact_id, after=updates)
    return after


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, user: dict = Depends(get_current_user)):
    before = await db.contacts.find_one({"id": contact_id, "org_id": user["org_id"]}, {"_id": 0})
    await db.contacts.delete_one({"id": contact_id, "org_id": user["org_id"]})
    await audit(user["org_id"], user, "delete", entity="contact", entity_id=contact_id, before=before)
    return {"ok": True}


# ---------------- Scripts ----------------
@router.get("/scripts")
async def list_scripts(user: dict = Depends(get_current_user)):
    return await db.scripts.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/scripts")
async def create_script(req: ScriptCreate, user: dict = Depends(get_current_user)):
    doc = {
        "id": new_id("script"), "org_id": user["org_id"], "name": req.name,
        "content": req.content, "objective": req.objective,
        "script_type": req.script_type or "line_by_line", "personality": req.personality or "",
        "created_at": now_utc().isoformat(),
    }
    await db.scripts.insert_one(dict(doc))
    await audit(user["org_id"], user, "create", entity="script", entity_id=doc["id"], after={"name": req.name, "script_type": doc["script_type"]})
    return clean(doc)


@router.post("/scripts/generate")
async def ai_generate_script(req: GenerateScriptRequest, user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    content = await generate_script(
        req.product, req.audience, req.objective, req.tone,
        session_id=f"script_{user['org_id']}", script_type=req.script_type,
        personality=req.personality, org=org)
    return {"content": content}


@router.put("/scripts/{script_id}")
async def update_script(script_id: str, req: ScriptUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    res = await db.scripts.update_one({"id": script_id, "org_id": user["org_id"]}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Script not found")
    return await db.scripts.find_one({"id": script_id}, {"_id": 0})


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, user: dict = Depends(get_current_user)):
    await db.scripts.delete_one({"id": script_id, "org_id": user["org_id"]})
    return {"ok": True}


# ---------------- Campaigns ----------------
@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(get_current_user)):
    camps = await db.campaigns.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for c in camps:
        c["call_count"] = await db.calls.count_documents({"campaign_id": c["id"]})
    return camps


@router.post("/campaigns")
async def create_campaign(req: CampaignCreate, user: dict = Depends(get_current_user)):
    doc = {
        "id": new_id("camp"), "org_id": user["org_id"], "name": req.name,
        "script_id": req.script_id, "voice_id": req.voice_id, "description": req.description or "",
        "status": "draft", "created_at": now_utc().isoformat(),
    }
    await db.campaigns.insert_one(dict(doc))
    await audit(user["org_id"], user, "create", entity="campaign", entity_id=doc["id"], after={"name": req.name})
    return clean(doc)


@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, req: CampaignUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    res = await db.campaigns.update_one({"id": campaign_id, "org_id": user["org_id"]}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Campaign not found")
    return await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, user: dict = Depends(get_current_user)):
    await db.campaigns.delete_one({"id": campaign_id, "org_id": user["org_id"]})
    return {"ok": True}


# ---------------- Voices ----------------
@router.get("/voices")
async def list_voices(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    enabled = bool((org or {}).get("integrations", {}).get("elevenlabs_api_key"))
    return {"voices": VOICE_CATALOG, "elevenlabs_enabled": enabled}


@router.post("/voices/preview")
async def voice_preview(req: VoicePreviewRequest, user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    result = await generate_tts(org, req.voice_id, req.text)
    # keep backward-compatible shape (mock flag) for the frontend
    result["mock"] = result["provider"] != "elevenlabs"
    return result


@router.post("/settings/integrations/elevenlabs/test")
async def test_elevenlabs(req: ElevenLabsTestRequest, user: dict = Depends(require_admin)):
    """Validate an ElevenLabs API key. Uses the posted key, or the saved one if blank."""
    key = req.api_key
    if not key:
        org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
        key = (org or {}).get("integrations", {}).get("elevenlabs_api_key", "")
    result = validate_elevenlabs_key(key)
    await audit(user["org_id"], user, "elevenlabs_key_test", detail=f"valid={result['valid']}", entity="integration")
    return result


@router.get("/llm/models")
async def llm_models(user: dict = Depends(get_current_user)):
    return get_llm_models()


@router.post("/settings/integrations/llm/test")
async def test_llm(req: LLMTestRequest, user: dict = Depends(require_admin)):
    """Validate a custom LLM provider key (OpenAI / Anthropic / Gemini)."""
    key = req.api_key
    if not key:
        org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
        field = {"openai": "openai_api_key", "anthropic": "anthropic_api_key", "gemini": "gemini_api_key"}.get(req.provider, "")
        key = (org or {}).get("integrations", {}).get(field, "")
    result = await validate_llm_key(req.provider, key, req.model)
    await audit(user["org_id"], user, "llm_key_test", detail=f"{req.provider} valid={result['valid']}", entity="integration")
    return result


# ---------------- Compliance helpers ----------------
def within_calling_hours(org: dict) -> dict:
    tz = ZoneInfo("Europe/London")
    nowt = datetime.now(tz)
    day_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today = day_map[nowt.weekday()]
    start = org.get("calling_hours_start", "08:00")
    end = org.get("calling_hours_end", "20:00")
    days = org.get("calling_days", ["mon", "tue", "wed", "thu", "fri"])
    cur = nowt.strftime("%H:%M")
    allowed = today in days and start <= cur <= end
    return {"allowed": allowed, "now": cur, "day": today, "start": start, "end": end, "days": days}


# ---------------- Test Calls ----------------
@router.post("/calls/test/start")
async def start_test_call(req: TestCallStartRequest, user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    script_id = req.script_id
    voice_id = req.voice_id
    if req.campaign_id:
        camp = await db.campaigns.find_one({"id": req.campaign_id, "org_id": user["org_id"]}, {"_id": 0})
        if camp:
            script_id = script_id or camp.get("script_id")
            voice_id = voice_id or camp.get("voice_id")
    script = await db.scripts.find_one({"id": script_id, "org_id": user["org_id"]}, {"_id": 0}) if script_id else None
    script_content = script["content"] if script else "Introduce yourself, your company, and your offer politely."
    script_type = (script or {}).get("script_type", "line_by_line")
    personality = (script or {}).get("personality", "")

    # Active company-overview documents power both the opening and live answers.
    active_kb = await get_kb_entries(user["org_id"], active_only=True)
    company_overview = "\n\n".join([f"[{e['title']}]\n{e['content'][:1500]}" for e in active_kb])

    # DNC / compliance check if contact linked
    contact = None
    if req.contact_id:
        contact = await db.contacts.find_one({"id": req.contact_id, "org_id": user["org_id"]}, {"_id": 0})
        if contact and contact.get("opted_out"):
            raise HTTPException(403, "Contact has opted out / is on the Do-Not-Call list.")

    # opening line — scripted (default) or KB-guided
    scripted_opening = "Hello, this is your AI assistant calling. Do you have a quick moment?"
    for line in script_content.split("\n"):
        if line.strip() and "[" not in line:
            scripted_opening = line.strip()
            break

    opening = scripted_opening
    opening_meta = {"mode": "scripted", "sources": [], "fallback": False, "reason": "scripted_default"}
    if (org or {}).get("opening_mode") == "kb":
        kb_entries = active_kb
        product_context = (script.get("objective") if script else "") or "Cold outreach call"
        kb_res = await generate_kb_opening(
            org, kb_entries, product_context,
            creativity=(org or {}).get("opening_creativity", "medium"),
            max_length=int((org or {}).get("opening_max_length", 220)),
            session_id=f"open_{user['org_id']}",
        )
        if kb_res["opening"] and not kb_res["fallback"]:
            opening = kb_res["opening"]
            opening_meta = {"mode": "kb", "sources": kb_res["sources"], "fallback": False, "reason": kb_res["reason"]}
        else:
            opening_meta = {"mode": "scripted", "sources": kb_res["sources"], "fallback": True, "reason": kb_res["reason"]}

    voice = get_voice(voice_id) if voice_id else None

    # TTS: deterministic provider selection (ElevenLabs when configured) — no silent fallback
    tts = await generate_tts(org, voice_id, opening) if voice_id else {"provider": "browser", "audio_url": None, "reason": "no_voice", "error": None}

    call = {
        "id": new_id("call"), "org_id": user["org_id"], "campaign_id": req.campaign_id,
        "contact_id": req.contact_id, "voice_id": voice_id, "voice_name": voice["name"] if voice else None,
        "script_id": script_id, "script_content": script_content, "is_test": True,
        "script_type": script_type, "personality": personality, "company_overview": company_overview,
        "status": "in_progress", "sentiment": None, "opted_out": False,
        "opening_meta": opening_meta, "tts_provider": tts["provider"],
        "transcript": [{"role": "agent", "content": opening, "ts": now_utc().isoformat()}],
        "created_at": now_utc().isoformat(),
    }
    await db.calls.insert_one(dict(call))
    return {
        "call_id": call["id"], "voice": voice, "opening": opening,
        "tts_provider": tts["provider"], "tts_reason": tts.get("reason"),
        "tts_error": tts.get("error"), "audio_url": tts.get("audio_url"),
        "opening_meta": opening_meta,
        "elevenlabs_enabled": select_tts_provider(org)["provider"] == "elevenlabs",
    }


@router.post("/calls/test/turn")
async def test_call_turn(req: TestCallTurnRequest, user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    call = await db.calls.find_one({"id": req.call_id, "org_id": user["org_id"]}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Call not found")
    history = call.get("transcript", [])
    history.append({"role": "prospect", "content": req.message, "ts": now_utc().isoformat()})
    reply = await agent_reply(
        call["script_content"], history, req.message, session_id=req.call_id,
        script_type=call.get("script_type", "line_by_line"), personality=call.get("personality", ""),
        company_overview=call.get("company_overview", ""), org=org)
    history.append({"role": "agent", "content": reply, "ts": now_utc().isoformat()})
    await db.calls.update_one({"id": req.call_id}, {"$set": {"transcript": history}})
    tts = await generate_tts(org, call.get("voice_id"), reply) if call.get("voice_id") else {"provider": "browser", "audio_url": None, "reason": "no_voice", "error": None}
    return {"reply": reply, "tts_provider": tts["provider"], "tts_reason": tts.get("reason"),
            "tts_error": tts.get("error"), "audio_url": tts.get("audio_url")}


@router.post("/calls/test/{call_id}/end")
async def end_test_call(call_id: str, user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    call = await db.calls.find_one({"id": call_id, "org_id": user["org_id"]}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Call not found")
    transcript_text = "\n".join([f"{t['role']}: {t['content']}" for t in call.get("transcript", [])])
    analysis = await analyze_transcript(transcript_text, session_id=call_id, org=org)
    await db.calls.update_one({"id": call_id}, {"$set": {
        "status": "completed", "sentiment": analysis.get("sentiment"),
        "opted_out": analysis.get("opted_out", False), "analysis": analysis,
        "ended_at": now_utc().isoformat(),
    }})
    # update linked contact
    if call.get("contact_id"):
        new_status = "opted_out" if analysis.get("opted_out") else (
            "positive" if analysis.get("sentiment") == "positive" else "contacted")
        await db.contacts.update_one(
            {"id": call["contact_id"], "org_id": user["org_id"]},
            {"$set": {"status": new_status, "sentiment": analysis.get("sentiment"),
                      "opted_out": bool(analysis.get("opted_out")), "last_called_at": now_utc().isoformat()}})
        if analysis.get("opted_out"):
            contact = await db.contacts.find_one({"id": call["contact_id"]}, {"_id": 0})
            if contact:
                await db.dnc_list.update_one(
                    {"org_id": user["org_id"], "phone": contact["phone"]},
                    {"$setOnInsert": {"id": new_id("dnc"), "org_id": user["org_id"], "phone": contact["phone"],
                                      "reason": "opted_out_on_call", "created_at": now_utc().isoformat()}},
                    upsert=True)
    return {"analysis": analysis}


@router.get("/calls")
async def list_calls(user: dict = Depends(get_current_user), is_test: bool = Query(None)):
    q = {"org_id": user["org_id"]}
    if is_test is not None:
        q["is_test"] = is_test
    return await db.calls.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.get("/calls/{call_id}")
async def get_call(call_id: str, user: dict = Depends(get_current_user)):
    c = await db.calls.find_one({"id": call_id, "org_id": user["org_id"]}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Call not found")
    return c


# ---------------- Compliance ----------------
@router.get("/compliance/overview")
async def compliance_overview(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    dnc_count = await db.dnc_list.count_documents({"org_id": user["org_id"]})
    opted = await db.contacts.count_documents({"org_id": user["org_id"], "opted_out": True})
    consented = await db.contacts.count_documents({"org_id": user["org_id"], "consent": True})
    total = await db.contacts.count_documents({"org_id": user["org_id"]})
    erasures = await db.erasure_requests.count_documents({"org_id": user["org_id"]})
    return {
        "calling_hours": within_calling_hours(org or {}),
        "dnc_count": dnc_count, "opted_out": opted, "consented": consented,
        "total_contacts": total, "erasure_requests": erasures,
    }


@router.get("/compliance/dnc")
async def list_dnc(user: dict = Depends(get_current_user)):
    return await db.dnc_list.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.post("/compliance/dnc")
async def add_dnc(req: DNCAddRequest, user: dict = Depends(get_current_user)):
    doc = {"id": new_id("dnc"), "org_id": user["org_id"], "phone": req.phone,
           "reason": req.reason, "created_at": now_utc().isoformat()}
    await db.dnc_list.update_one({"org_id": user["org_id"], "phone": req.phone},
                                 {"$setOnInsert": doc}, upsert=True)
    await db.contacts.update_many({"org_id": user["org_id"], "phone": req.phone},
                                  {"$set": {"status": "dnc", "opted_out": True}})
    await audit(user["org_id"], user, "dnc_add", req.phone)
    return clean(doc)


@router.delete("/compliance/dnc/{dnc_id}")
async def remove_dnc(dnc_id: str, user: dict = Depends(get_current_user)):
    await db.dnc_list.delete_one({"id": dnc_id, "org_id": user["org_id"]})
    await audit(user["org_id"], user, "dnc_remove", dnc_id)
    return {"ok": True}


@router.get("/compliance/check")
async def check_number(phone: str = Query(...), user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    dnc = await db.dnc_list.find_one({"org_id": user["org_id"], "phone": phone})
    hours = within_calling_hours(org or {})
    callable_now = (dnc is None) and hours["allowed"]
    return {"phone": phone, "on_dnc": dnc is not None, "calling_hours": hours, "callable": callable_now}


@router.post("/compliance/erasure")
async def gdpr_erasure(req: ErasureRequest, user: dict = Depends(get_current_user)):
    contact = await db.contacts.find_one({"id": req.contact_id, "org_id": user["org_id"]}, {"_id": 0})
    if not contact:
        raise HTTPException(404, "Contact not found")
    await db.erasure_requests.insert_one({
        "id": new_id("erasure"), "org_id": user["org_id"], "contact_name": contact["name"],
        "contact_phone": contact["phone"], "requested_by": user["email"], "created_at": now_utc().isoformat(),
    })
    await db.calls.delete_many({"contact_id": req.contact_id, "org_id": user["org_id"]})
    await db.contacts.delete_one({"id": req.contact_id, "org_id": user["org_id"]})
    await audit(user["org_id"], user, "gdpr_erasure", contact["phone"])
    return {"ok": True, "message": "Contact and associated call records permanently erased (GDPR Art. 17)."}


@router.get("/compliance/erasure")
async def list_erasures(user: dict = Depends(get_current_user)):
    return await db.erasure_requests.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)


# ---------------- Settings: Org ----------------
@router.get("/settings/org")
async def get_org(user: dict = Depends(get_current_user)):
    return await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})


@router.put("/settings/org")
async def update_org(req: OrgUpdateRequest, user: dict = Depends(require_admin)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    await db.organizations.update_one({"id": user["org_id"]}, {"$set": updates})
    await audit(user["org_id"], user, "org_update", str(list(updates.keys())))
    return await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})


# ---------------- Settings: Integrations ----------------
@router.get("/settings/integrations")
async def get_integrations(user: dict = Depends(require_admin)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    return (org or {}).get("integrations", {})


@router.put("/settings/integrations")
async def update_integrations(req: IntegrationSettings, user: dict = Depends(require_admin)):
    await db.organizations.update_one({"id": user["org_id"]}, {"$set": {"integrations": req.model_dump()}})
    await audit(user["org_id"], user, "integrations_update", "")
    return req.model_dump()


@router.post("/settings/integrations/tcx/test")
async def test_tcx(user: dict = Depends(require_admin)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    if not integ.get("tcx_url"):
        raise HTTPException(400, "3CX URL not configured")
    # MOCK: real 3CX Call Control API connection would be validated here.
    return {"ok": True, "mock": True, "message": f"Mock connection to 3CX at {integ['tcx_url']} succeeded. (Live calls require a reachable 3CX Call Control API.)"}


# ---------------- User Management ----------------
@router.get("/users")
async def list_users(user: dict = Depends(require_admin)):
    users = await db.users.find({"org_id": user["org_id"]}, {"_id": 0, "password_hash": 0}).to_list(500)
    return users


@router.post("/users")
async def invite_user(req: InviteUserRequest, user: dict = Depends(require_admin)):
    email = req.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already exists")
    doc = {
        "id": new_id("user"), "org_id": user["org_id"], "email": email, "name": req.name,
        "password_hash": hash_password(req.password), "role": req.role,
        "auth_provider": "password", "picture": "", "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(dict(doc))
    await audit(user["org_id"], user, "user_invite", email)
    doc.pop("password_hash", None)
    return clean(doc)


@router.put("/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, user: dict = Depends(require_admin)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    await db.users.update_one({"id": user_id, "org_id": user["org_id"]}, {"$set": updates})
    return await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(400, "You cannot remove yourself")
    await db.users.delete_one({"id": user_id, "org_id": user["org_id"]})
    await audit(user["org_id"], user, "user_delete", user_id)
    return {"ok": True}


@router.get("/audit")
async def list_audit(user: dict = Depends(require_admin)):
    return await db.audit_logs.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
