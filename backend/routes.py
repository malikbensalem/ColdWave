import logging
import asyncio
import csv
import io
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body
from database import db
from auth import get_current_user, require_admin, hash_password, require_perm, require_cap, user_can
from models import (
    ContactCreate, ContactUpdate, ScriptCreate, ScriptUpdate, GenerateScriptRequest,
    CampaignCreate, CampaignUpdate, VoicePreviewRequest, TestCallStartRequest,
    TestCallTurnRequest, DNCAddRequest, ErasureRequest, OrgUpdateRequest,
    IntegrationSettings, InviteUserRequest, UpdateUserRequest, ElevenLabsTestRequest,
    LLMTestRequest, VoiceCharacteristicsUpdate, BanRequest, DialRequest, TcxTestRequest, TwilioTestRequest, TakeoverRequest, CampaignLeadsRequest, now_utc, new_id,
)
from telephony import (
    test_connection as telephony_test, make_call as telephony_make_call,
    twilio_make_call as telephony_twilio_call, twilio_update_call, twilio_hangup_call,
)
from integrations import (
    VOICE_CATALOG, get_voice, generate_voice_preview, generate_script,
    agent_reply, analyze_transcript, generate_tts, select_tts_provider,
    validate_elevenlabs_key, generate_kb_opening, generate_opening_line, get_llm_models, validate_llm_key, llm_config,
    get_elevenlabs_models, inworld_ping, inworld_list_voices,
    generate_tts_inworld, _pcm16_to_wav_b64,
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


async def build_campaign_call_context(org: dict, campaign: dict) -> dict:
    """Build the same AI context as Test Calls (script/blueprint/voice/opening) for a live call."""
    org = await attach_system_prefix(org)
    script_id = (campaign or {}).get("script_id")
    voice_id = (campaign or {}).get("voice_id")
    script = await db.scripts.find_one({"id": script_id, "org_id": org["id"]}, {"_id": 0}) if script_id else None
    script_content = script["content"] if script else "Introduce yourself, your company, and your offer politely."
    script_type = (script or {}).get("script_type", "line_by_line")
    personality = (script or {}).get("personality", "")
    active_kb = await get_kb_entries(org["id"], active_only=True)
    company_overview = "\n\n".join([f"[{e['title']}]\n{e['content'][:1500]}" for e in active_kb])
    voice = get_voice(voice_id) if voice_id else None
    ov = (org or {}).get("voice_characteristics", {}).get(voice_id, {}) if voice_id else {}
    vname = ov.get("name") or (voice["name"] if voice else "your assistant")
    vpersona = ov.get("persona") or (voice.get("persona", "") if voice else "")
    if voice:
        company_overview = f"[YOUR IDENTITY]\nYour name is {vname}. {vpersona}\n\n{company_overview}".strip()

    import re as _re
    opening = None
    if script and script_type == "line_by_line":
        for line in script_content.split("\n"):
            s = _re.sub(r"^\s*\[[^\]]*\]\s*", "", line).strip()
            if s:
                opening = s
                break
    if opening is None:
        try:
            gen = await generate_opening_line(org, script_content, personality, script_type, company_overview, vname, f"open_{org['id']}")
            opening = gen or None
        except Exception:
            opening = None
    if opening is None:
        opening = f"Hi, this is {vname}. Do you have a quick moment?"

    return {"script_id": script_id, "voice_id": voice_id, "voice_name": voice["name"] if voice else None,
            "script_content": script_content, "script_type": script_type, "personality": personality,
            "company_overview": company_overview, "opening": opening}


async def place_outbound_call(integ: dict, destination: str, say_text: str = None,
                              voice_url: str = None, status_url: str = None, amd_url: str = None,
                              call_id: str = None) -> dict:
    """Route an outbound call to the tenant's selected provider (3CX, Twilio or Telnyx).
    Returns {result, provider, extension}. Raises HTTPException with a clear message."""
    provider = (integ.get("telephony_provider") or "3cx").lower()
    if provider == "telnyx":
        if not integ.get("telnyx_enabled"):
            raise HTTPException(400, "Telnyx is selected but not enabled. Enable Telnyx in Settings → Integrations.")
        if not (integ.get("telnyx_api_key") and integ.get("telnyx_connection_id") and integ.get("telnyx_phone_number")):
            raise HTTPException(400, "Telnyx needs an API key, Connection ID and phone number in Settings → Integrations.")
        from telnyx_voice import telnyx_make_call
        try:
            result = await telnyx_make_call(integ, destination, call_id)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"Could not place call via Telnyx: {str(e)[:160]}")
        return {"result": result, "provider": "telnyx", "extension": integ.get("telnyx_phone_number", "")}
    if provider == "twilio":
        if not integ.get("twilio_enabled"):
            raise HTTPException(400, "Twilio is selected but not enabled. Enable Twilio in Settings → Integrations.")
        try:
            result = await telephony_twilio_call(integ, destination, say_text, voice_url=voice_url, status_url=status_url, amd_url=amd_url)
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


def _twilio_webhooks(call_id: str, integ: dict = None) -> tuple:
    """Return (voice_url, status_url, amd_url). All Twilio AI calls use the ConversationRelay
    streaming webhook (low-latency, interruptible)."""
    from twilio_voice import public_base_url
    base = public_base_url()
    voice = f"{base}/api/telephony/twilio/relay/voice/{call_id}"
    return (voice, f"{base}/api/telephony/twilio/status/{call_id}",
            f"{base}/api/telephony/twilio/amd/{call_id}")


async def attach_system_prefix(org: dict, channel: str = "call") -> dict:
    """Resolve the effective AI system prefix (channel blueprint → org blueprint → org extension)."""
    if not org:
        return org
    bp_id = (org.get("channel_blueprints") or {}).get(channel) or org.get("blueprint_id")
    bp_prompt = ""
    if bp_id:
        bp = await db.ai_blueprints.find_one({"id": bp_id}, {"_id": 0})
        bp_prompt = (bp or {}).get("prompt", "")
    parts = [p for p in [bp_prompt] if p]
    return {**org, "_system_prefix": "\n\n".join(parts)} if parts else org


# ---------------- Dashboard ----------------
@router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    org_id = user["org_id"]
    contacts = await db.contacts.find({"org_id": org_id}, {"_id": 0}).to_list(5000)
    calls = await db.calls.find({"org_id": org_id, "is_test": {"$ne": True}}, {"_id": 0}).to_list(5000)
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
    calls = await db.calls.find({"org_id": user["org_id"], "contact_id": {"$in": ids}, "is_test": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(20000)
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
    name = (req.name or "").strip() or " ".join(x for x in [(req.first_name or "").strip(), (req.last_name or "").strip()] if x).strip()
    if not name:
        raise HTTPException(400, "Please provide a name or first/last name.")
    doc = {
        "id": new_id("contact"), "org_id": user["org_id"], "name": name,
        "first_name": req.first_name or "", "last_name": req.last_name or "", "phone": req.phone,
        "email": req.email or "", "company": req.company or "", "notes": req.notes or "",
        "consent": req.consent, "status": "dnc" if dnc else (req.status or "new"), "opted_out": bool(dnc),
        "lead_status": req.lead_status or "", "lead_owner": req.lead_owner or "",
        "lead_owner_alias": req.lead_owner_alias or "", "lead_source": req.lead_source or "",
        "hs_traffic_category": req.hs_traffic_category or "",
        "sentiment": None, "last_called_at": None, "created_at": now_utc().isoformat(),
    }
    await db.contacts.insert_one(dict(doc))
    await audit(user["org_id"], user, "create", entity="contact", entity_id=doc["id"], after=doc)
    return clean(doc)


# ---------------- CRM CSV import ----------------
def _norm_phone(p: str) -> str:
    """Digits-only normalized phone for duplicate matching (last 10 digits)."""
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


# Maps normalized (lowercased, trimmed) CSV headers -> our contact field.
_CSV_HEADER_MAP = {
    "first name": "first_name", "firstname": "first_name",
    "last name": "last_name", "lastname": "last_name",
    "full name": "name", "name": "name", "contact name": "name",
    "mobile phone": "phone", "mobile phone number": "phone", "phone": "phone",
    "phone number": "phone", "mobile": "phone", "mobile number": "phone",
    "email": "email", "email address": "email",
    "company": "company", "company / account": "company", "company/account": "company",
    "account": "company", "company name": "company",
    "lead notes": "notes", "notes": "notes",
    "lead status": "lead_status", "status": "lead_status",
    "lead owner": "lead_owner", "owner": "lead_owner",
    "lead owner alias": "lead_owner_alias", "owner alias": "lead_owner_alias",
    "lead source": "lead_source", "source": "lead_source",
    "hs-traffic-category": "hs_traffic_category", "hs traffic category": "hs_traffic_category",
    "traffic category": "hs_traffic_category",
    "created date": "created_date", "create date": "created_date", "created": "created_date",
    "last activity date": "last_activity_date", "last activity": "last_activity_date",
    "last contacted date": "last_contacted_date", "last contacted": "last_contacted_date",
    "last contact date": "last_contacted_date",
}


@router.post("/contacts/import")
async def import_contacts(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Import CRM leads from a HubSpot-style CSV. Always creates new contacts and flags
    potential duplicates (matching phone or email of an existing lead)."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file.")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10 MB).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "The CSV appears to be empty.")

    colmap = {}  # original header -> our field
    for h in reader.fieldnames:
        key = (h or "").strip().lower()
        if key in _CSV_HEADER_MAP:
            colmap[h] = _CSV_HEADER_MAP[key]

    org_id = user["org_id"]
    # Existing keys for duplicate detection.
    existing = await db.contacts.find({"org_id": org_id}, {"_id": 0, "phone": 1, "email": 1}).to_list(20000)
    seen_phones = {_norm_phone(c.get("phone", "")) for c in existing if c.get("phone")}
    seen_emails = {(c.get("email") or "").strip().lower() for c in existing if c.get("email")}
    dnc_rows = await db.dnc_list.find({"org_id": org_id}, {"_id": 0, "phone": 1}).to_list(20000)
    dnc_phones = {_norm_phone(d.get("phone", "")) for d in dnc_rows}

    created, duplicates, skipped, errors = 0, 0, 0, []
    docs = []
    for i, row in enumerate(reader, start=2):  # header is row 1
        vals = {}
        first = last = ""
        for orig, field in colmap.items():
            v = (row.get(orig) or "").strip()
            if field == "first_name":
                first = v
            elif field == "last_name":
                last = v
            elif v:
                vals[field] = v
        name = vals.get("name") or " ".join(x for x in [first, last] if x).strip()
        phone = vals.get("phone", "")
        email = vals.get("email", "")
        if not name and not phone and not email:
            continue  # blank row
        if not name:
            name = phone or email
        if not phone:
            errors.append(f"Row {i}: missing phone — skipped.")
            skipped += 1
            continue

        np, ne = _norm_phone(phone), email.strip().lower()
        is_dup = (np and np in seen_phones) or (ne and ne in seen_emails)
        dup_reason = ""
        if is_dup:
            dup_reason = "Matches an existing lead's phone or email."
            duplicates += 1
        seen_phones.add(np)
        if ne:
            seen_emails.add(ne)

        on_dnc = np in dnc_phones
        doc = {
            "id": new_id("contact"), "org_id": org_id, "name": name, "phone": phone,
            "email": email, "company": vals.get("company", ""), "notes": vals.get("notes", ""),
            "consent": False, "status": "dnc" if on_dnc else "new", "opted_out": on_dnc,
            "sentiment": None, "last_called_at": None, "created_at": now_utc().isoformat(),
            "first_name": first, "last_name": last,
            "lead_status": vals.get("lead_status", ""), "lead_owner": vals.get("lead_owner", ""),
            "lead_owner_alias": vals.get("lead_owner_alias", ""), "lead_source": vals.get("lead_source", ""),
            "hs_traffic_category": vals.get("hs_traffic_category", ""),
            "lead_created_date": vals.get("created_date", ""),
            "last_activity_date": vals.get("last_activity_date", ""),
            "last_contacted_date": vals.get("last_contacted_date", ""),
            "is_potential_duplicate": is_dup, "duplicate_reason": dup_reason,
            "source_import": file.filename,
        }
        docs.append(doc)
        created += 1

    if docs:
        await db.contacts.insert_many([dict(d) for d in docs])
    await audit(org_id, user, "import", detail=f"Imported {created} leads from {file.filename}", entity="contact")
    return {"created": created, "duplicates": duplicates, "skipped": skipped,
            "errors": errors[:20], "mapped_columns": list(set(colmap.values()))}


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
    # When a callback is scheduled, move the lead to the callback stage AND tag their most
    # recent (answered) call as a callback so it's clear that call produced a callback.
    if updates.get("callback_at"):
        updates.setdefault("status", "callback")
        last_call = await db.calls.find_one(
            {"org_id": user["org_id"], "contact_id": contact_id, "is_test": {"$ne": True},
             "status": {"$nin": ["no_answer"]}},
            {"_id": 0, "id": 1}, sort=[("created_at", -1)])
        if last_call:
            await db.calls.update_one({"id": last_call["id"]}, {"$set": {
                "is_callback": True, "outcome": "callback",
                "callback_at": updates["callback_at"], "callback_type": updates.get("callback_type", "human")}})
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


@router.post("/contacts/{contact_id}/allow-calling")
async def allow_calling(contact_id: str, user: dict = Depends(get_current_user)):
    """Take a lead off the Do-Not-Call list and make them callable again."""
    contact = await db.contacts.find_one({"id": contact_id, "org_id": user["org_id"]}, {"_id": 0})
    if not contact:
        raise HTTPException(404, "Contact not found")
    await db.dnc_list.delete_many({"org_id": user["org_id"], "phone": contact["phone"]})
    await db.contacts.update_one({"id": contact_id, "org_id": user["org_id"]},
                                 {"$set": {"opted_out": False, "status": "new"}})
    await audit(user["org_id"], user, "allow_calling", contact["phone"], entity="contact", entity_id=contact_id)
    return await db.contacts.find_one({"id": contact_id}, {"_id": 0})


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
    return await db.calls.find({"org_id": org_id, "campaign_id": campaign_id, "is_test": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(20000)


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
    asyncio.create_task(_warm_campaign_cache(user["org_id"], doc["id"]))
    return clean(doc)


@router.post("/campaigns/{campaign_id}/warm-cache")
async def warm_campaign_cache(campaign_id: str, user: dict = Depends(get_current_user)):
    # Run in the background so the request returns immediately (synthesis can take several seconds).
    asyncio.create_task(_warm_campaign_cache(user["org_id"], campaign_id))
    return {"ok": True, "status": "warming"}


async def _warm_campaign_cache(org_id: str, campaign_id: str) -> int:
    """Pre-synthesize a campaign's opening + common static phrases into the TTS cache so the
    first spoken words on a live call are instant. No-op unless a telephony TTS provider is set."""
    from integrations import generate_tts_telephony, select_tts_provider
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0})
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": org_id}, {"_id": 0})
    if not org or not camp:
        return 0
    if select_tts_provider(org).get("provider") not in ("inworld", "elevenlabs"):
        return 0
    try:
        ctx = await build_campaign_call_context(org, camp)
    except Exception:
        return 0
    phrases = [p for p in [
        ctx.get("opening"),
        "Are you still there?",
        "No problem, I'll let you go. Thanks for your time, goodbye.",
        "Sorry, could you say that again?",
    ] if p]
    warmed = 0
    for text in phrases:
        try:
            res = await generate_tts_telephony(org, text, voice_id=camp.get("voice_id"))
            if res.get("audio_b64"):
                warmed += 1
        except Exception as e:
            logger.error(f"warm-cache phrase failed: {e}")
    logger.info(f"warm-cache campaign={campaign_id} warmed {warmed}/{len(phrases)} phrases")
    return warmed


@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, req: CampaignUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    res = await db.campaigns.update_one({"id": campaign_id, "org_id": user["org_id"]}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Campaign not found")
    if "voice_id" in updates or "script_id" in updates:
        asyncio.create_task(_warm_campaign_cache(user["org_id"], campaign_id))
    return await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, user: dict = Depends(get_current_user)):
    await db.campaigns.delete_one({"id": campaign_id, "org_id": user["org_id"]})
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/leads")
async def manage_campaign_leads(campaign_id: str, req: CampaignLeadsRequest, user: dict = Depends(get_current_user)):
    """Add or remove specific leads on a campaign (converts audience to 'specific')."""
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": user["org_id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "Campaign not found")
    ids = list(dict.fromkeys(camp.get("contact_ids") or []))
    if req.action == "add":
        for cid in req.contact_ids:
            if cid not in ids:
                ids.append(cid)
    else:
        ids = [c for c in ids if c not in set(req.contact_ids)]
    await db.campaigns.update_one({"id": campaign_id, "org_id": user["org_id"]},
                                  {"$set": {"contact_ids": ids, "audience": "specific"}})
    await audit(user["org_id"], user, req.action, entity="campaign", entity_id=campaign_id,
                detail=f"{req.action} {len(req.contact_ids)} lead(s)")
    return await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})


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
            "outcome": cl.get("outcome"), "voicemail": bool(cl.get("voicemail")),
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

    ctx = await build_campaign_call_context(org, camp)
    provider = (integ.get("telephony_provider") or "3cx").lower()
    call_id = new_id("call")
    call_doc = {
        "id": call_id, "org_id": user["org_id"], "type": "campaign", "campaign_id": campaign_id,
        "contact_id": contact["id"], "contact_name": contact.get("name", ""),
        "destination": contact["phone"], "is_test": False,
        "voice_id": ctx["voice_id"], "voice_name": ctx["voice_name"], "script_id": ctx["script_id"],
        "script_content": ctx["script_content"], "script_type": ctx["script_type"],
        "personality": ctx["personality"], "company_overview": ctx["company_overview"],
        "opening": ctx["opening"], "transcript": [{"role": "agent", "content": ctx["opening"], "ts": now_utc().isoformat()}],
        "provider": provider, "status": "initiating",
        "agent_id": user["id"], "agent_email": user["email"], "created_at": now_utc().isoformat(),
    }
    await db.calls.insert_one(dict(call_doc))

    voice_url, status_url, amd_url = (_twilio_webhooks(call_id, integ) if provider == "twilio" else (None, None, None))
    try:
        call = await place_outbound_call(integ, contact["phone"], say_text=ctx["opening"], voice_url=voice_url, status_url=status_url, amd_url=amd_url, call_id=call_id)
    except HTTPException:
        await db.calls.delete_one({"id": call_id})
        raise
    result = call["result"]
    await db.calls.update_one({"id": call_id}, {"$set": {
        "extension": call["extension"], "callid": result.get("callid"),
        "provider_call_sid": result.get("callid"), "status": result.get("status", "Initiated")}})
    if contact.get("status") in (None, "new"):
        await db.contacts.update_one({"id": contact["id"], "org_id": user["org_id"]}, {"$set": {"status": "contacted"}})
    if camp.get("status") == "draft":
        await db.campaigns.update_one({"id": campaign_id}, {"$set": {"status": "active"}})
    await audit(user["org_id"], user, "campaign_dial", contact["phone"], entity="campaign", entity_id=campaign_id)
    call_doc.pop("_id", None)
    return {"ok": True, "dialed": {"name": contact["name"], "phone": contact["phone"]},
            "call_id": call_id, "callid": result.get("callid"), "status": result.get("status"),
            "remaining": queue.get("upcoming_count", 0) - 1}


# ---------------- Campaign auto-dialer ----------------
_auto_dial_tasks = {}  # campaign_id -> asyncio.Task


async def _set_auto_dial(campaign_id: str, org_id: str, active: bool, reason: str = ""):
    await db.campaigns.update_one({"id": campaign_id, "org_id": org_id}, {"$set": {
        "auto_dial": {"active": active, "reason": reason, "updated_at": now_utc().isoformat()}}})


async def _wait_for_call_end(call_id: str, timeout: int = 200) -> str:
    """Poll a call until it reaches a terminal state (or timeout)."""
    terminal = {"completed", "no_answer", "failed", "busy", "canceled"}
    waited = 0
    while waited < timeout:
        await asyncio.sleep(3)
        waited += 3
        c = await db.calls.find_one({"id": call_id}, {"_id": 0, "status": 1, "analysis": 1, "voicemail": 1})
        if not c:
            return "gone"
        st = (c.get("status") or "").lower()
        if st in terminal or c.get("analysis") or c.get("voicemail"):
            return st or "completed"
    return "timeout"


async def _auto_dial_loop(org_id: str, campaign_id: str, user: dict, pause: int = 4):
    logger.info(f"auto-dial START campaign={campaign_id}")
    try:
        while True:
            camp = await db.campaigns.find_one({"id": campaign_id, "org_id": org_id}, {"_id": 0})
            if not camp or not (camp.get("auto_dial") or {}).get("active"):
                break
            org = await db.organizations.find_one({"id": org_id}, {"_id": 0})
            if not within_calling_hours(org or {}).get("allowed", True):
                await _set_auto_dial(campaign_id, org_id, False, "Paused — outside calling hours.")
                break
            queue = await campaign_queue(campaign_id, user)
            if not queue.get("next"):
                await _set_auto_dial(campaign_id, org_id, False, "Finished — no more contacts in the queue.")
                break
            try:
                res = await campaign_dial_next(campaign_id, user)
            except HTTPException as e:
                await _set_auto_dial(campaign_id, org_id, False, f"Stopped: {e.detail}")
                break
            except Exception as e:
                await _set_auto_dial(campaign_id, org_id, False, f"Stopped: {str(e)[:120]}")
                break
            call_id = res.get("call_id")
            if call_id:
                await _wait_for_call_end(call_id)
            await asyncio.sleep(pause)
    finally:
        _auto_dial_tasks.pop(campaign_id, None)
        logger.info(f"auto-dial END campaign={campaign_id}")


@router.post("/campaigns/{campaign_id}/auto-dial/start")
async def auto_dial_start(campaign_id: str, user: dict = Depends(require_perm("leads", "read"))):
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": user["org_id"]}, {"_id": 0})
    if not camp:
        raise HTTPException(404, "Campaign not found")
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    provider = (integ.get("telephony_provider") or "3cx").lower()
    if provider == "twilio" and not integ.get("twilio_enabled"):
        raise HTTPException(400, "Twilio is selected but not enabled. Enable it in Settings → Integrations.")
    if provider == "telnyx" and not integ.get("telnyx_enabled"):
        raise HTTPException(400, "Telnyx is selected but not enabled. Enable it in Settings → Integrations.")
    if provider == "3cx" and not integ.get("tcx_enabled"):
        raise HTTPException(400, "3CX live calling is not enabled. Configure it in Settings → Integrations.")
    if not within_calling_hours(org or {}).get("allowed", True):
        raise HTTPException(400, "Outside your configured calling hours — auto-dial can't start right now.")
    queue = await campaign_queue(campaign_id, user)
    if not queue.get("next"):
        raise HTTPException(400, "The campaign queue is empty — nothing to auto-dial.")
    if campaign_id in _auto_dial_tasks and not _auto_dial_tasks[campaign_id].done():
        return {"ok": True, "already_running": True}
    await _set_auto_dial(campaign_id, user["org_id"], True, "Auto-dialing…")
    # Minimal user context needed by the loop's helper calls.
    uctx = {"id": user["id"], "org_id": user["org_id"], "email": user["email"]}
    _auto_dial_tasks[campaign_id] = asyncio.create_task(_auto_dial_loop(user["org_id"], campaign_id, uctx))
    await audit(user["org_id"], user, "auto_dial_start", "", entity="campaign", entity_id=campaign_id)
    return {"ok": True, "queued": queue.get("upcoming_count", 0)}


@router.post("/campaigns/{campaign_id}/auto-dial/stop")
async def auto_dial_stop(campaign_id: str, user: dict = Depends(require_perm("leads", "read"))):
    await _set_auto_dial(campaign_id, user["org_id"], False, "Stopped by user.")
    t = _auto_dial_tasks.get(campaign_id)
    if t and not t.done():
        t.cancel()
    await audit(user["org_id"], user, "auto_dial_stop", "", entity="campaign", entity_id=campaign_id)
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/auto-dial/status")
async def auto_dial_status(campaign_id: str, user: dict = Depends(get_current_user)):
    camp = await db.campaigns.find_one({"id": campaign_id, "org_id": user["org_id"]}, {"_id": 0, "auto_dial": 1})
    if camp is None:
        raise HTTPException(404, "Campaign not found")
    state = camp.get("auto_dial") or {"active": False}
    queue = await campaign_queue(campaign_id, user)
    return {"active": bool(state.get("active")), "reason": state.get("reason", ""),
            "upcoming_count": queue.get("upcoming_count", 0), "contacted_count": queue.get("contacted_count", 0),
            "next": queue.get("next")}


# ---------------- Voices ----------------
@router.get("/voices")
async def list_voices(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    overrides = (org or {}).get("voice_characteristics", {})
    # When Inworld is the selected Voice-AI provider, surface Inworld voices (same shape the UI uses).
    if integ.get("tts_stt_provider") == "inworld" and (integ.get("inworld_api_key") or "").strip():
        iw = await inworld_list_voices(org)
        voices = []
        for v in iw.get("voices", []):
            vid = v.get("voiceId")
            if not vid:
                continue
            ov = overrides.get(vid, {})
            voices.append({
                "id": vid, "name": v.get("displayName") or vid,
                "gender": v.get("gender") or "neutral", "accent": v.get("langCode") or "",
                "description": f"Inworld voice ({v.get('langCode', '')})".strip(),
                "persona": ov.get("persona", ""),
                "display_name": ov.get("name") or v.get("displayName") or vid,
                "speed": ov.get("speed", 1.0), "stability": ov.get("stability", 0.5),
                "style": ov.get("style", 0.0), "dynamic": bool(ov.get("dynamic", False)),
                "provider": "inworld", "customized": bool(ov.get("name") or ov.get("persona")),
            })
        return {"voices": voices, "provider": "inworld", "source": iw.get("source"),
                "error": iw.get("error"), "elevenlabs_enabled": False}
    enabled = bool(integ.get("elevenlabs_api_key") and integ.get("elevenlabs_enabled"))
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
            "provider": "elevenlabs",
            "customized": bool(ov.get("name") or ov.get("persona") or ov.get("speed") or ov.get("dynamic") or ov.get("stability") is not None),
        })
    # Append the user's custom ElevenLabs voice (if pasted in Settings).
    custom_id = (integ.get("elevenlabs_custom_voice_id") or "").strip()
    if custom_id:
        ov = overrides.get("custom", {})
        voices.append({
            "id": "custom", "name": integ.get("elevenlabs_custom_voice_name") or "Custom voice",
            "gender": integ.get("elevenlabs_custom_voice_gender") or "female", "accent": "Custom",
            "description": "Your custom ElevenLabs voice (from your account).",
            "persona": ov.get("persona", ""), "elevenlabs_voice_id": custom_id,
            "display_name": ov.get("name") or integ.get("elevenlabs_custom_voice_name") or "Custom voice",
            "speed": ov.get("speed", 1.0), "stability": ov.get("stability", 0.5),
            "style": ov.get("style", 0.0), "dynamic": bool(ov.get("dynamic", False)),
            "is_custom": True, "customized": False,
        })
    return {"voices": voices, "provider": "elevenlabs", "elevenlabs_enabled": enabled}


@router.put("/voices/{voice_id}/characteristics")
async def update_voice_characteristics(voice_id: str, req: VoiceCharacteristicsUpdate, user: dict = Depends(require_admin)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    if not get_voice(voice_id, org):
        raise HTTPException(404, "Voice not found")
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
    # When Inworld is the active Voice-AI provider, preview with a real Inworld voice (WAV for browser).
    if select_tts_provider(org).get("provider") == "inworld":
        res = await generate_tts_inworld(org, req.text, voice_id=req.voice_id,
                                         encoding="LINEAR16", sample_rate=24000, use_cache=False)
        if res.get("audio_b64"):
            wav = _pcm16_to_wav_b64(res["audio_b64"], 24000)
            return {"provider": "inworld", "mock": False, "audio_url": f"data:audio/wav;base64,{wav}",
                    "voice": None, "error": None}
        return {"provider": "inworld_error", "mock": True, "audio_url": None, "voice": None, "error": res.get("error")}
    result = await generate_tts(org, req.voice_id, req.text)
    # keep backward-compatible shape (mock flag) for the frontend
    result["mock"] = result["provider"] != "elevenlabs"
    return result


@router.post("/inworld/preview")
async def inworld_preview(body: dict = Body(default={}), user: dict = Depends(get_current_user)):
    """Preview an Inworld voice regardless of the active provider (used in Settings)."""
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    voice_id = body.get("voice_id") or integ.get("inworld_tts_voice_id")
    text = body.get("text") or "Hi, this is a preview of your selected Inworld voice on ColdWave."
    if not voice_id:
        return {"audio_url": None, "error": "Select an Inworld voice first."}
    res = await generate_tts_inworld(org, text, voice_id=voice_id,
                                     encoding="LINEAR16", sample_rate=24000, use_cache=False)
    if res.get("audio_b64"):
        return {"audio_url": f"data:audio/wav;base64,{_pcm16_to_wav_b64(res['audio_b64'], 24000)}", "error": None}
    return {"audio_url": None, "error": res.get("error")}


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


@router.post("/settings/integrations/telnyx/test")
async def test_telnyx(body: dict = Body(default={}), user: dict = Depends(require_admin)):
    """Validate a Telnyx API key + connection id. Uses posted values or saved ones."""
    from telnyx_voice import telnyx_validate
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    saved = (org or {}).get("integrations", {})
    integ = {"telnyx_api_key": body.get("telnyx_api_key") or saved.get("telnyx_api_key", ""),
             "telnyx_connection_id": body.get("telnyx_connection_id") or saved.get("telnyx_connection_id", "")}
    result = await telnyx_validate(integ)
    await audit(user["org_id"], user, "telnyx_key_test", detail=f"valid={result.get('valid')}", entity="integration")
    return result


@router.post("/settings/integrations/inworld/test")
async def test_inworld(body: dict = Body(default={}), user: dict = Depends(require_admin)):
    """Validate an Inworld API key via a lightweight voices ping."""
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    key = body.get("inworld_api_key") or (org or {}).get("integrations", {}).get("inworld_api_key", "")
    result = await inworld_ping(key)
    await audit(user["org_id"], user, "inworld_key_test", detail=f"valid={result.get('valid')}", entity="integration")
    return result


@router.get("/inworld/voices")
async def inworld_voices(user: dict = Depends(get_current_user)):
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    return await inworld_list_voices(org)


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
    _cfg = llm_config(org)
    return {
        "call_id": call["id"], "voice": voice, "opening": opening,
        "tts_provider": tts["provider"], "tts_reason": tts.get("reason"),
        "tts_error": tts.get("error"), "audio_url": tts.get("audio_url"),
        "opening_meta": opening_meta,
        "llm_provider": _cfg["provider"], "llm_model": _cfg["model"],
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


LIVE_STATUSES = ["initiating", "Initiated", "queued", "ringing", "in-progress", "in_progress", "answered", "Dialing"]


@router.get("/calls/live/active")
async def list_live_calls(user: dict = Depends(get_current_user)):
    """Active (non-completed) calls for live monitoring, newest first."""
    q = {"org_id": user["org_id"], "is_test": {"$ne": True},
         "status": {"$in": LIVE_STATUSES}, "analysis": {"$exists": False}}
    calls = await db.calls.find(q, {"_id": 0, "script_content": 0, "company_overview": 0}).sort("created_at", -1).to_list(100)
    return calls


@router.post("/calls/{call_id}/takeover")
async def takeover_call(call_id: str, req: TakeoverRequest, user: dict = Depends(require_perm("leads", "read"))):
    """Instantly hand a live AI call over to a human by redirecting the Twilio call to a human number."""
    call = await db.calls.find_one({"id": call_id, "org_id": user["org_id"]}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Call not found")
    sid = call.get("provider_call_sid") or call.get("callid")
    if call.get("provider") != "twilio" or not sid:
        raise HTTPException(400, "Live takeover is available only on active Twilio streaming calls.")
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    human = (req.human_number or "").strip().replace(" ", "")
    if not human:
        raise HTTPException(400, "A human phone number is required to take over the call.")
    from xml.sax.saxutils import escape as _esc
    twiml = (f'<Response><Say voice="Polly.Amy" language="en-GB">Please hold, connecting you now.</Say>'
             f'<Dial>{_esc(human)}</Dial></Response>')
    try:
        await twilio_update_call(integ, sid, twiml)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Takeover failed: {str(e)[:160]}")
    tx = (call.get("transcript") or [])
    tx.append({"role": "system", "content": f"Call handed over to human ({human}).", "ts": now_utc().isoformat()})
    await db.calls.update_one({"id": call_id}, {"$set": {
        "handoff": True, "handoff_to": human, "handoff_by": user["email"], "transcript": tx}})
    await audit(user["org_id"], user, "call_takeover", human, entity="call", entity_id=call_id)
    return {"ok": True}


@router.post("/calls/{call_id}/hangup")
async def hangup_call(call_id: str, user: dict = Depends(require_perm("leads", "read"))):
    """End a live Twilio call."""
    call = await db.calls.find_one({"id": call_id, "org_id": user["org_id"]}, {"_id": 0})
    if not call:
        raise HTTPException(404, "Call not found")
    sid = call.get("provider_call_sid") or call.get("callid")
    if call.get("provider") != "twilio" or not sid:
        raise HTTPException(400, "Ending a live call is available only on active Twilio calls.")
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    try:
        await twilio_hangup_call(integ, sid)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Hangup failed: {str(e)[:160]}")
    await db.calls.update_one({"id": call_id}, {"$set": {"status": "completed", "ended_by": user["email"]}})
    await audit(user["org_id"], user, "call_hangup", "", entity="call", entity_id=call_id)
    return {"ok": True}


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
    row = await db.dnc_list.find_one({"id": dnc_id, "org_id": user["org_id"]}, {"_id": 0})
    await db.dnc_list.delete_one({"id": dnc_id, "org_id": user["org_id"]})
    # Re-enable any matching contact so they can be called again.
    if row and row.get("phone"):
        await db.contacts.update_many(
            {"org_id": user["org_id"], "phone": row["phone"], "status": {"$in": ["dnc", "opted_out"]}},
            {"$set": {"opted_out": False, "status": "new"}})
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
    # Never expose the `integrations` object (Twilio/ElevenLabs/LLM/O365 secrets) here —
    # it is available only to admins via GET /settings/integrations.
    return await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0, "integrations": 0})


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
    return await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0, "integrations": 0})


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


@router.get("/settings/integrations/balances")
async def integration_balances(user: dict = Depends(require_admin)):
    """Live remaining credits/balance per connected integration (best-effort)."""
    import httpx
    org = await db.organizations.find_one({"id": user["org_id"]}, {"_id": 0})
    integ = (org or {}).get("integrations", {})
    out = []

    # ElevenLabs — characters remaining this billing period.
    el_key = integ.get("elevenlabs_api_key", "")
    if el_key:
        item = {"provider": "elevenlabs", "label": "ElevenLabs", "unit": "characters", "ok": False, "detail": "", "value": None, "total": None}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": el_key})
            if r.status_code == 200:
                d = r.json()
                used, limit = d.get("character_count", 0), d.get("character_limit", 0)
                remaining = max(0, (limit or 0) - (used or 0))
                item.update({"ok": True, "value": remaining, "total": limit,
                             "detail": f"{remaining:,} of {limit:,} characters left ({d.get('tier', 'plan')})"})
            elif r.status_code in (401, 403):
                item["detail"] = "Invalid API key."
            else:
                item["detail"] = f"ElevenLabs HTTP {r.status_code}."
        except Exception as e:
            item["detail"] = f"Could not reach ElevenLabs: {str(e)[:80]}"
        out.append(item)

    # Twilio — account balance.
    sid, token = integ.get("twilio_account_sid", ""), integ.get("twilio_auth_token", "")
    if sid and token:
        item = {"provider": "twilio", "label": "Twilio", "unit": "balance", "ok": False, "detail": "", "value": None, "total": None}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Balance.json", auth=(sid, token))
            if r.status_code == 200:
                d = r.json()
                bal, cur = d.get("balance"), d.get("currency", "USD")
                item.update({"ok": True, "value": bal, "detail": f"{bal} {cur} remaining"})
            elif r.status_code in (401, 403):
                item["detail"] = "Invalid Account SID or Auth Token."
            else:
                item["detail"] = f"Twilio HTTP {r.status_code}."
        except Exception as e:
            item["detail"] = f"Could not reach Twilio: {str(e)[:80]}"
        out.append(item)

    # Telnyx — account balance.
    tk = integ.get("telnyx_api_key", "")
    if tk:
        item = {"provider": "telnyx", "label": "Telnyx", "unit": "balance", "ok": False, "detail": "", "value": None, "total": None}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.telnyx.com/v2/balance", headers={"Authorization": f"Bearer {tk}"})
            if r.status_code == 200:
                d = r.json().get("data", {})
                bal, cur = d.get("balance"), d.get("currency", "USD")
                avail = d.get("available_credit")
                detail = f"{bal} {cur} balance"
                if avail is not None:
                    detail += f" · {avail} {cur} available credit"
                item.update({"ok": True, "value": f"{bal} {cur}", "detail": detail})
            elif r.status_code in (401, 403):
                item["detail"] = "Invalid Telnyx API key."
            else:
                item["detail"] = f"Telnyx HTTP {r.status_code}."
        except Exception as e:
            item["detail"] = f"Could not reach Telnyx: {str(e)[:80]}"
        out.append(item)

    # 3CX — no billing/credit API.
    if integ.get("tcx_url"):
        out.append({"provider": "3cx", "label": "3CX", "unit": "n/a", "ok": True, "value": None, "total": None,
                    "detail": "3CX has no credit/balance API — usage is billed on your PBX plan."})

    # LLM provider — balance not exposed by a public API.
    prov = integ.get("llm_provider", "anthropic")
    if integ.get(f"{prov}_api_key"):
        out.append({"provider": prov, "label": f"{prov.capitalize()} (LLM)", "unit": "n/a", "ok": True, "value": None,
                    "total": None, "detail": "Check remaining credit on your provider dashboard — no public balance API."})

    return {"balances": out, "checked_at": now_utc().isoformat()}


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

    # Build the AI context (script/blueprint/voice/opening) — same pipeline as Test Calls.
    campaign = None
    if req.campaign_id:
        campaign = await db.campaigns.find_one({"id": req.campaign_id, "org_id": user["org_id"]}, {"_id": 0})
        if not campaign:
            raise HTTPException(404, "Campaign not found")
    ctx = await build_campaign_call_context(org, campaign)

    provider = (integ.get("telephony_provider") or "3cx").lower()
    call_id = new_id("call")
    call_doc = {
        "id": call_id, "org_id": user["org_id"], "type": "manual",
        "contact_id": req.contact_id, "contact_name": (contact or {}).get("name", ""),
        "campaign_id": req.campaign_id, "destination": destination, "is_test": False,
        "voice_id": ctx["voice_id"], "voice_name": ctx["voice_name"], "script_id": ctx["script_id"],
        "script_content": ctx["script_content"], "script_type": ctx["script_type"],
        "personality": ctx["personality"], "company_overview": ctx["company_overview"],
        "opening": ctx["opening"], "transcript": [{"role": "agent", "content": ctx["opening"], "ts": now_utc().isoformat()}],
        "provider": provider, "status": "initiating",
        "agent_id": user["id"], "agent_email": user["email"], "created_at": now_utc().isoformat(),
    }
    await db.calls.insert_one(dict(call_doc))

    # For Twilio, drive the call through the AI voice webhook (campaign voice + script + blueprint).
    voice_url, status_url, amd_url = (_twilio_webhooks(call_id, integ) if provider == "twilio" else (None, None, None))
    try:
        call = await place_outbound_call(integ, destination, say_text=ctx["opening"], voice_url=voice_url, status_url=status_url, amd_url=amd_url, call_id=call_id)
    except HTTPException:
        await db.calls.delete_one({"id": call_id})
        raise
    result = call["result"]
    await db.calls.update_one({"id": call_id}, {"$set": {
        "extension": call["extension"], "callid": result.get("callid"),
        "provider_call_sid": result.get("callid"), "status": result.get("status", "Initiated")}})
    if contact and contact.get("status") in (None, "new"):
        await db.contacts.update_one({"id": contact["id"], "org_id": user["org_id"]}, {"$set": {"status": "contacted"}})
    await audit(user["org_id"], user, "manual_call", destination, entity="contact", entity_id=req.contact_id)
    call_doc.update({"extension": call["extension"], "callid": result.get("callid"), "status": result.get("status")})
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
