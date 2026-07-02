import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from database import db
from auth import get_current_user, require_admin, hash_password, require_perm, require_cap, user_can
from models import (
    ContactCreate, ContactUpdate, ScriptCreate, ScriptUpdate, GenerateScriptRequest,
    CampaignCreate, CampaignUpdate, VoicePreviewRequest, TestCallStartRequest,
    TestCallTurnRequest, DNCAddRequest, ErasureRequest, OrgUpdateRequest,
    IntegrationSettings, InviteUserRequest, UpdateUserRequest, ElevenLabsTestRequest,
    LLMTestRequest, VoiceCharacteristicsUpdate, BanRequest, DialRequest, TcxTestRequest, TwilioTestRequest, now_utc, new_id,
)
from telephony import test_connection as telephony_test, make_call as telephony_make_call, twilio_make_call as telephony_twilio_call
from integrations import (
    VOICE_CATALOG, get_voice, generate_voice_preview, generate_script,
    agent_reply, analyze_transcript, generate_tts, select_tts_provider,
    validate_elevenlabs_key, generate_kb_opening, generate_opening_line, get_llm_models, validate_llm_key, llm_config,
    get_elevenlabs_models,
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


async def place_outbound_call(integ: dict, destination: str, say_text: str = None) -> dict:
    """Route an outbound call to the tenant's selected provider (3CX or Twilio).
    Returns {result, provider, extension}. Raises HTTPException with a clear message."""
    provider = (integ.get("telephony_provider") or "3cx").lower()
    if provider == "twilio":
        if not integ.get("twilio_enabled"):
            raise HTTPException(400, "Twilio is selected but not enabled. Enable Twilio in Settings → Integrations.")
        try:
            result = await telephony_twilio_call(integ, destination, say_text)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"Could not place call via Twilio: {str(e)[:160]}")
        return {"result": result, "provider": "twilio", "extension": integ.get("twilio_phone_number", "")}
    # default: 3CX
    if not integ.get("tcx_enabled"):
        raise HTTPException(400, "3CX live calling is not enabled. Select Twilio, or configure and enable 3CX in Settings → Integrations.")
    try:
        result = await telephony_make_call(integ, destination)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not place call via 3CX: {str(e)[:160]}")
    return {"result": result, "provider": "3cx", "extension": integ.get("tcx_extension", "")}


async def attach_system_prefix(org: dict, channel: str = "call") -> dict:
    """Resolve the effective AI system prefix (channel blueprint → org blueprint → org extension)."""
    if not org:
        return org
    bp_id = (org.get("channel_blueprints") or {}).get(channel) or org.get("blueprint_id")
    bp_prompt = ""
    if bp_id:
        bp = await db.ai_blueprints.find_one({"id": bp_id}, {"_id": 0})
        bp_prompt = (bp or {}).get("prompt", "")
    org_p = org.get("ai_system_prompt", "")
    parts = [p for p in [bp_prompt, org_p] if p]
    return {**org, "_system_prefix": "\n\n".join(parts)} if parts else org


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
async def _campaign_name_map(org_id: str) -> dict:
    camps = await db.campaigns.find({"org_id": org_id}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    return {c["id"]: c["name"] for c in camps}


def _enrich_call(call: dict, cmap: dict) -> dict:
    analysis = call.get("analysis") or {}
    return {
        **call,
        "campaign_name": cmap.get(call.get("campaign_id"), "—") if call.get("campaign_id") else "—",
        "rating": call.get("rating", analysis.get("score")),
        "summary": call.get("summary", analysis.get("summary", "")),
        "next_action": analysis.get("next_action", ""),
    }


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
    contacts = await db.contacts.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    # Attach latest-call summary + call count per contact for the CRM table.
    cmap = await _campaign_name_map(user["org_id"])
    ids = [c["id"] for c in contacts]
    calls = await db.calls.find({"org_id": user["org_id"], "contact_id": {"$in": ids}}, {"_id": 0}).sort("created_at", -1).to_list(20000)
    by_contact = {}
    for cl in calls:
        cid = cl.get("contact_id")
        by_contact.setdefault(cid, []).append(cl)
    for c in contacts:
        cl = by_contact.get(c["id"], [])
        c["call_count"] = len(cl)
        if cl:
            latest = _enrich_call(cl[0], cmap)
            c["last_call_status"] = latest.get("status")
            c["last_call_rating"] = latest.get("rating")
            c["last_call_summary"] = latest.get("summary")
            c["last_call_campaign"] = latest.get("campaign_name")
            c["last_call_date"] = latest.get("created_at")
        else:
            c["last_call_status"] = None
            c["last_call_rating"] = None
            c["last_call_summary"] = ""
            c["last_call_campaign"] = "—"
            c["last_call_date"] = None
    return contacts


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
    cmap = await _campaign_name_map(user["org_id"])
    c["calls"] = [_enrich_call(cl, cmap) for cl in c["calls"]]
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
    org = await attach_system_prefix(org)
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
CAMPAIGN_AUDIENCE_QUERY = {
    "all": {},
    "new": {"status": "new"},
    "positive": {"status": "positive"},
    "contacted": {"status": "contacted"},
    "callback": {"status": "callback"},
    "consented": {"consent": True},
}


async def _campaign_calls(org_id: str, campaign_id: str) -> list:
    return await db.calls.find({"org_id": org_id, "campaign_id": campaign_id}, {"_id": 0}).sort("created_at", -1).to_list(20000)


def _campaign_analytics(calls: list) -> dict:
    ratings = []
    for c in calls:
        r = c.get("rating")
        if r is None:
            r = (c.get("analysis") or {}).get("score")
        if isinstance(r, (int, float)):
            ratings.append(r)
    completed = [c for c in calls if c.get("status") == "completed"]
    positive = [c for c in calls if c.get("sentiment") == "positive"]
    return {
        "times_used": len(calls),
        "total_calls": len(calls),
        "completed": len(completed),
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "positive": len(positive),
        "positive_rate": round(len(positive) / len(calls) * 100) if calls else 0,
        "sentiment": {
            "positive": len(positive),
            "neutral": len([c for c in calls if c.get("sentiment") == "neutral"]),
            "negative": len([c for c in calls if c.get("sentiment") == "negative"]),
        },
    }


@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(get_current_user)):
    camps = await db.campaigns.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for c in camps:
        calls = await _campaign_calls(user["org_id"], c["id"])
        c["call_count"] = len(calls)
        c["analytics"] = _campaign_analytics(calls)
    return camps


@router.post("/campaigns")
async def create_campaign(req: CampaignCreate, user: dict = Depends(get_current_user)):
    audience = "specific" if req.contact_ids else req.audience
    doc = {
        "id": new_id("camp"), "org_id": user["org_id"], "name": req.name,
        "script_id": req.script_id, "voice_id": req.voice_id, "description": req.description or "",
        "audience": audience, "contact_ids": req.contact_ids or [],
        "schedule_type": req.schedule_type, "scheduled_at": req.scheduled_at,
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


@router.get("/campaigns/{campaign_id}/analytics")
async def campaign_analytics(campaign_id: str, user: dict = Depends(get_current_user)):
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": user["org_id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "Campaign not found")
    calls = await _campaign_calls(user["org_id"], campaign_id)
    return {"campaign": camp, **_campaign_analytics(calls)}


@router.get("/campaigns/{campaign_id}/queue")
async def campaign_queue(campaign_id: str, user: dict = Depends(get_current_user)):
    """Who has been called on this campaign, who's next, and the upcoming audience queue."""
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": user["org_id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "Campaign not found")
    cmap = await _campaign_name_map(user["org_id"])
    calls = await _campaign_calls(user["org_id"], campaign_id)

    # Contacted: latest call per contact for this campaign.
    contacted = []
    seen = set()
    called_ids = set()
    for cl in calls:
        cid = cl.get("contact_id")
        if not cid:
            continue
        called_ids.add(cid)
        if cid in seen:
            continue
        seen.add(cid)
        contact = await db.contacts.find_one({"id": cid, "org_id": user["org_id"]}, {"_id": 0})
        enriched = _enrich_call(cl, cmap)
        contacted.append({
            "contact_id": cid, "name": (contact or {}).get("name", "—"),
            "phone": (contact or {}).get("phone", ""), "company": (contact or {}).get("company", ""),
            "rating": enriched.get("rating"), "sentiment": cl.get("sentiment"),
            "summary": enriched.get("summary"), "status": cl.get("status"), "called_at": cl.get("created_at"),
        })

    # Upcoming: audience-matched (or the campaign's specific clients) not yet called; skip opted-out/DNC.
    specific_ids = camp.get("contact_ids") or []
    if camp.get("audience") == "specific" and specific_ids:
        q = {"org_id": user["org_id"], "id": {"$in": specific_ids},
             "opted_out": {"$ne": True}, "status": {"$nin": ["opted_out", "dnc"]}}
    else:
        q = {"org_id": user["org_id"], "opted_out": {"$ne": True},
             "status": {"$nin": ["opted_out", "dnc"]}}
        q.update(CAMPAIGN_AUDIENCE_QUERY.get(camp.get("audience", "all"), {}))
    audience_contacts = await db.contacts.find(q, {"_id": 0}).sort("created_at", 1).to_list(5000)
    upcoming = [
        {"contact_id": c["id"], "name": c["name"], "phone": c["phone"], "company": c.get("company", ""), "status": c.get("status")}
        for c in audience_contacts if c["id"] not in called_ids
    ]
    return {
        "campaign": camp,
        "audience": camp.get("audience", "all"),
        "contacted": contacted,
        "contacted_count": len(contacted),
        "upcoming": upcoming[:200],
        "upcoming_count": len(upcoming),
        "next": upcoming[0] if upcoming else None,
    }


@router.post("/campaigns/{campaign_id}/dial-next")
async def campaign_dial_next(campaign_id: str, user: dict = Depends(require_perm("leads", "read"))):
    """Originate a live call (3CX or Twilio, per settings) to the next contact in the campaign queue."""
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": user["org_id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "Campaign not found")
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})

    queue = await campaign_queue(campaign_id, user)
    nxt = queue.get("next")
    if not nxt:
        raise HTTPException(400, "The campaign queue is empty — no more contacts to dial.")
    contact = await db.contacts.find_one({"id": nxt["contact_id"], "org_id": user["org_id"]}, {"_id": 0})
    if not contact or not contact.get("phone"):
        raise HTTPException(400, "Next contact has no phone number.")

    say_text = None
    if camp.get("script_id"):
        script = await db.scripts.find_one({"id": camp["script_id"], "org_id": user["org_id"]}, {"_id": 0})
        if script:
            import re as _re
            for line in (script.get("content") or "").split("\n"):
                s = _re.sub(r"^\s*\[[^\]]*\]\s*", "", line).strip()
                if s:
                    say_text = s
                    break

    call = await place_outbound_call(integ, contact["phone"], say_text)
    result = call["result"]

    call_doc = {
        "id": new_id("call"), "org_id": user["org_id"], "type": "campaign", "campaign_id": campaign_id,
        "contact_id": contact["id"], "contact_name": contact.get("name", ""),
        "destination": contact["phone"], "extension": call["extension"],
        "provider": call["provider"], "callid": result.get("callid"), "status": result.get("status", "Initiated"),
        "agent_id": user["id"], "agent_email": user["email"], "created_at": now_utc().isoformat(),
    }
    await db.calls.insert_one(dict(call_doc))
    if contact.get("status") in (None, "new"):
        await db.contacts.update_one({"id": contact["id"], "org_id": user["org_id"]}, {"$set": {"status": "contacted"}})
    if camp.get("status") == "draft":
        await db.campaigns.update_one({"id": campaign_id}, {"$set": {"status": "active"}})
    await audit(user["org_id"], user, "campaign_dial", contact["phone"], entity="campaign", entity_id=campaign_id)
    call_doc.pop("_id", None)
    return {"ok": True, "dialed": {"name": contact["name"], "phone": contact["phone"]},
            "callid": result.get("callid"), "status": result.get("status"),
            "remaining": queue.get("upcoming_count", 0) - 1}


# ---------------- Voices ----------------
@router.get("/voices")
async def list_voices(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    enabled = bool(integ.get("elevenlabs_api_key") and integ.get("elevenlabs_enabled"))
    overrides = (org or {}).get("voice_characteristics", {})
    voices = []
    for v in VOICE_CATALOG:
        ov = overrides.get(v["id"], {})
        voices.append({
            **v,
            "display_name": ov.get("name") or v["name"],
            "persona": ov.get("persona") or v.get("persona", ""),
            "speed": ov.get("speed", 1.0),
            "stability": ov.get("stability", 0.5),
            "style": ov.get("style", 0.0),
            "dynamic": bool(ov.get("dynamic", False)),
            "customized": bool(ov.get("name") or ov.get("persona") or ov.get("speed") or ov.get("dynamic") or ov.get("stability") is not None),
        })
    return {"voices": voices, "elevenlabs_enabled": enabled}


@router.put("/voices/{voice_id}/characteristics")
async def update_voice_characteristics(voice_id: str, req: VoiceCharacteristicsUpdate, user: dict = Depends(require_admin)):
    if not get_voice(voice_id):
        raise HTTPException(404, "Voice not found")
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    chars = (org or {}).get("voice_characteristics", {})
    cur = chars.get(voice_id, {})
    if req.name is not None:
        cur["name"] = req.name
    if req.persona is not None:
        cur["persona"] = req.persona
    if req.speed is not None:
        cur["speed"] = max(0.7, min(1.2, float(req.speed)))
    if req.stability is not None:
        cur["stability"] = max(0.0, min(1.0, float(req.stability)))
    if req.style is not None:
        cur["style"] = max(0.0, min(1.0, float(req.style)))
    if req.dynamic is not None:
        cur["dynamic"] = bool(req.dynamic)
    chars[voice_id] = cur
    await db.organizations.update_one({"id": user["org_id"]}, {"$set": {"voice_characteristics": chars}})
    await audit(user["org_id"], user, "voice_characteristics_update", voice_id, entity="voice", entity_id=voice_id, after=cur)
    return {"voice_id": voice_id, **cur}


@router.get("/elevenlabs/models")
async def elevenlabs_models(user: dict = Depends(get_current_user)):
    return {"models": get_elevenlabs_models()}


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
    org = await attach_system_prefix(org)
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

    voice = get_voice(voice_id) if voice_id else None
    ov = (org or {}).get("voice_characteristics", {}).get(voice_id, {}) if voice_id else {}
    vname = ov.get("name") or (voice["name"] if voice else "your assistant")
    vpersona = ov.get("persona") or (voice.get("persona", "") if voice else "")

    # Inject the voice's identity (name + persona) so the agent knows who it is if asked.
    if voice:
        identity = f"Your name is {vname}. {vpersona}".strip()
        company_overview = f"[YOUR IDENTITY]\n{identity}\n\n{company_overview}".strip()

    # ---- Opening line resolution (depends on script/blueprint, not a fixed string) ----
    import re as _re
    opening, opening_meta = None, None

    # 1) Line-by-line script: use its first spoken line (strip [STAGE] labels).
    if script and script_type == "line_by_line":
        for line in script_content.split("\n"):
            stripped = _re.sub(r"^\s*\[[^\]]*\]\s*", "", line).strip()
            if stripped:
                opening = stripped
                opening_meta = {"mode": "scripted", "sources": [], "fallback": False, "reason": "script_first_line"}
                break

    # 2) KB-guided opening (org setting).
    if opening is None and (org or {}).get("opening_mode") == "kb":
        product_context = (script.get("objective") if script else "") or "Cold outreach call"
        kb_res = await generate_kb_opening(
            org, active_kb, product_context,
            creativity=(org or {}).get("opening_creativity", "medium"),
            max_length=int((org or {}).get("opening_max_length", 220)),
            session_id=f"open_{user['org_id']}",
        )
        if kb_res["opening"] and not kb_res["fallback"]:
            opening = kb_res["opening"]
            opening_meta = {"mode": "kb", "sources": kb_res["sources"], "fallback": False, "reason": kb_res["reason"]}

    # 3) Personality-driven (or no usable scripted line): generate from persona + blueprint.
    if opening is None:
        gen = await generate_opening_line(
            org, script_content, personality, script_type, company_overview, vname, f"open_{user['org_id']}")
        if gen:
            opening = gen
            opening_meta = {"mode": "blueprint", "sources": [], "fallback": False, "reason": "persona_generated"}

    # 4) Final persona-aware fallback (LLM unavailable).
    if opening is None:
        opening = f"Hi, this is {vname}. Do you have a quick moment?"
        opening_meta = {"mode": "fallback", "sources": [], "fallback": True, "reason": "llm_unavailable"}

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
    org = await attach_system_prefix(org)
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


@router.get("/settings/branding")
async def get_branding(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0}) or {}
    return {
        "brand_name": org.get("brand_name", ""),
        "logo_url": org.get("logo_url", ""),
        "primary_color": org.get("primary_color", ""),
    }


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
    # Merge only the fields actually sent (exclude_unset) so a partial save never wipes other secrets.
    updates = req.model_dump(exclude_unset=True)
    if updates:
        await db.organizations.update_one(
            {"id": user["org_id"]},
            {"$set": {f"integrations.{k}": v for k, v in updates.items()}})
    await audit(user["org_id"], user, "integrations_update", "")
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    return (org or {}).get("integrations", {})


@router.post("/settings/integrations/tcx/test")
async def test_tcx(req: TcxTestRequest, user: dict = Depends(require_admin)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    saved = (org or {}).get("integrations", {})
    # Use the values sent in the request (current form input) and fall back to
    # saved values for any field left unset — no need to save before testing.
    integ = {
        "tcx_url": req.tcx_url if req.tcx_url is not None else saved.get("tcx_url", ""),
        "tcx_extension": req.tcx_extension if req.tcx_extension is not None else saved.get("tcx_extension", ""),
        "tcx_username": req.tcx_username if req.tcx_username is not None else saved.get("tcx_username", ""),
        "tcx_password": req.tcx_password if req.tcx_password is not None else saved.get("tcx_password", ""),
        "tcx_verify_tls": req.tcx_verify_tls if req.tcx_verify_tls is not None else saved.get("tcx_verify_tls", True),
    }
    if not integ.get("tcx_url"):
        raise HTTPException(400, "3CX URL not configured")
    try:
        return await telephony_test(integ)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not reach 3CX: {str(e)[:160]}")


@router.post("/settings/integrations/twilio/test")
async def test_twilio(req: TwilioTestRequest, user: dict = Depends(require_admin)):
    """Validate Twilio credentials by fetching the account (no SDK needed — Basic-auth REST)."""
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    saved = (org or {}).get("integrations", {})
    sid = (req.account_sid if req.account_sid is not None else saved.get("twilio_account_sid", "")).strip()
    token = (req.auth_token if req.auth_token is not None else saved.get("twilio_auth_token", "")).strip()
    if not sid or not token:
        raise HTTPException(400, "Enter your Twilio Account SID and Auth Token first.")
    import httpx
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, auth=(sid, token))
    except Exception as e:
        return {"valid": False, "message": f"Could not reach Twilio: {str(e)[:120]}"}
    if r.status_code == 200:
        d = r.json()
        return {"valid": True, "message": f"Twilio connected — account '{d.get('friendly_name', sid)}' ({d.get('status')})."}
    if r.status_code in (401, 403):
        return {"valid": False, "message": "Invalid Account SID or Auth Token."}
    return {"valid": False, "message": f"Twilio returned HTTP {r.status_code}."}


@router.post("/calls/dial")
async def dial_contact(req: DialRequest, user: dict = Depends(require_perm("leads", "read"))):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})

    contact = None
    destination = req.destination
    if req.contact_id:
        contact = await db.contacts.find_one({"id": req.contact_id, "org_id": user["org_id"]}, {"_id": 0})
        if not contact:
            raise HTTPException(404, "Contact not found")
        if contact.get("opted_out") or contact.get("do_not_call"):
            raise HTTPException(400, "This contact has opted out / is on the Do Not Call list.")
        destination = destination or contact.get("phone")
    if not destination:
        raise HTTPException(400, "No phone number to dial.")

    # Optional campaign selected from the CRM — logs the call against it and seeds the Twilio opening.
    campaign = None
    say_text = None
    if req.campaign_id:
        campaign = await db.campaigns.find_one({"id": req.campaign_id, "org_id": user["org_id"]}, {"_id": 0})
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        if campaign.get("script_id"):
            script = await db.scripts.find_one({"id": campaign["script_id"], "org_id": user["org_id"]}, {"_id": 0})
            if script:
                import re as _re
                for line in (script.get("content") or "").split("\n"):
                    s = _re.sub(r"^\s*\[[^\]]*\]\s*", "", line).strip()
                    if s:
                        say_text = s
                        break

    call = await place_outbound_call(integ, destination, say_text)
    result = call["result"]

    call_doc = {
        "id": new_id("call"), "org_id": user["org_id"], "type": "manual",
        "contact_id": req.contact_id, "contact_name": (contact or {}).get("name", ""),
        "campaign_id": req.campaign_id, "destination": destination, "extension": call["extension"],
        "provider": call["provider"], "callid": result.get("callid"), "status": result.get("status", "Initiated"),
        "agent_id": user["id"], "agent_email": user["email"], "created_at": now_utc().isoformat(),
    }
    await db.calls.insert_one(dict(call_doc))
    if contact and contact.get("status") in (None, "new"):
        await db.contacts.update_one({"id": contact["id"], "org_id": user["org_id"]}, {"$set": {"status": "contacted"}})
    await audit(user["org_id"], user, "manual_call", destination, entity="contact", entity_id=req.contact_id)
    call_doc.pop("_id", None)
    return {"ok": True, "callid": result.get("callid"), "status": result.get("status"), "provider": call["provider"], "call": clean(call_doc)}


# ---------------- User Management ----------------
@router.get("/users")
async def list_users(user: dict = Depends(require_perm("users", "read"))):
    users = await db.users.find({"org_id": user["org_id"]}, {"_id": 0, "password_hash": 0}).to_list(500)
    return users


@router.post("/users")
async def invite_user(req: InviteUserRequest, user: dict = Depends(require_perm("users", "create"))):
    email = req.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already exists")
    if req.role == "owner":
        raise HTTPException(400, "Cannot assign the owner role.")
    doc = {
        "id": new_id("user"), "org_id": user["org_id"], "email": email, "name": req.name,
        "password_hash": hash_password(req.password), "role": req.role,
        "auth_provider": "password", "picture": "", "banned": False, "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(dict(doc))
    await audit(user["org_id"], user, "user_invite", email)
    doc.pop("password_hash", None)
    return clean(doc)


@router.put("/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, user: dict = Depends(require_perm("users", "update"))):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if updates.get("role") == "owner":
        raise HTTPException(400, "Cannot assign the owner role.")
    await db.users.update_one({"id": user_id, "org_id": user["org_id"]}, {"$set": updates})
    return await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})


@router.post("/users/{user_id}/ban")
async def ban_user(user_id: str, req: BanRequest, user: dict = Depends(require_cap("ban_users"))):
    if user_id == user["id"]:
        raise HTTPException(400, "You cannot ban yourself")
    target = await db.users.find_one({"id": user_id, "org_id": user["org_id"]}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("role") == "owner":
        raise HTTPException(400, "The owner cannot be banned.")
    await db.users.update_one({"id": user_id, "org_id": user["org_id"]}, {"$set": {
        "banned": True, "ban_reason": req.reason, "banned_by": user["email"], "banned_at": now_utc().isoformat(),
    }})
    await audit(user["org_id"], user, "user_ban", req.reason, entity="user", entity_id=user_id)
    return {"ok": True}


@router.post("/users/{user_id}/unban")
async def unban_user(user_id: str, user: dict = Depends(require_cap("ban_users"))):
    await db.users.update_one({"id": user_id, "org_id": user["org_id"]},
                              {"$set": {"banned": False}, "$unset": {"ban_reason": "", "banned_by": "", "banned_at": ""}})
    await audit(user["org_id"], user, "user_unban", "", entity="user", entity_id=user_id)
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_perm("users", "delete"))):
    if user_id == user["id"]:
        raise HTTPException(400, "You cannot remove yourself")
    await db.users.delete_one({"id": user_id, "org_id": user["org_id"]})
    await audit(user["org_id"], user, "user_delete", user_id)
    return {"ok": True}


@router.get("/audit")
async def list_audit(user: dict = Depends(require_perm("audit", "read"))):
    return await db.audit_logs.find({"org_id": user["org_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
