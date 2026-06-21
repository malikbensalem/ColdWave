import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from database import db, create_indexes
from auth import auth_router, seed_admin, seed_owner, get_current_user, require_admin, require_owner
from routes import router as app_router
from models import now_utc, new_id
from audit import audit_context_middleware, record_audit, build_audit_router
from messaging import build_messaging_router, build_whatsapp_webhook_router, create_messaging_indexes
from kb import build_kb_router
from admin import build_admin_router
from email_campaigns import build_email_router, email_scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _validate_env():
    required = ["MONGO_URL", "DB_NAME", "JWT_SECRET"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Copy backend/.env.example to backend/.env and fill them in."
        )
    if not os.environ.get("EMERGENT_LLM_KEY"):
        logger.warning("EMERGENT_LLM_KEY not set — AI features (scripts, test-call, opening KB) will fail.")
    if not (os.environ.get("WHATSAPP_ACCESS_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID")):
        logger.warning("WhatsApp credentials not set — WhatsApp runs in MOCK mode (no real sends).")


_validate_env()

app = FastAPI(title="ColdWave AI Calling Platform")

# Per-request audit context (source IP + correlation id) for the append-only audit log.
app.middleware("http")(audit_context_middleware)


@app.get("/api/")
async def root():
    return {"message": "ColdWave AI Calling API", "status": "ok"}


@app.get("/api/health")
async def health():
    services = {"api": "ok"}
    try:
        await db.command("ping")
        services["mongodb"] = "ok"
    except Exception as e:
        services["mongodb"] = f"error: {e}"
    services["whatsapp"] = "live" if os.environ.get("WHATSAPP_ACCESS_TOKEN") else "mock"
    services["elevenlabs"] = "configured" if os.environ.get("ELEVENLABS_API_KEY") else "per-workspace/mock"
    services["llm"] = "configured" if os.environ.get("EMERGENT_LLM_KEY") else "missing"
    return {"status": "ok", "services": services}


app.include_router(auth_router)
app.include_router(app_router)
app.include_router(build_audit_router(get_current_user, require_admin))
app.include_router(build_messaging_router(get_current_user, record_audit))
app.include_router(build_whatsapp_webhook_router())
app.include_router(build_kb_router(get_current_user, record_audit))
app.include_router(build_admin_router(get_current_user, require_owner, record_audit))
app.include_router(build_email_router(get_current_user, require_admin, record_audit))

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)


async def seed_demo_data():
    admin = await db.users.find_one({"email": os.environ.get("ADMIN_EMAIL", "admin@coldwave.ai").lower()})
    if not admin:
        return
    org_id = admin["org_id"]
    if await db.contacts.count_documents({"org_id": org_id}) > 0:
        return
    script_id = new_id("script")
    await db.scripts.insert_one({
        "id": script_id, "org_id": org_id, "name": "SaaS Demo Booking Script",
        "objective": "Book a product demo",
        "content": ("[OPENING] Hi, this is Alex from ColdWave. Have I caught you at an okay time?\n"
                    "[HOOK] We help UK sales teams automate cold outreach with compliant AI voice calls.\n"
                    "[QUALIFYING QUESTIONS] Are you currently doing any outbound calling?\n"
                    "[VALUE PROPOSITION] Teams using us see 3x more booked meetings with full TPS/GDPR compliance.\n"
                    "[OBJECTION HANDLING] If they say 'no time' — offer to send info or call back.\n"
                    "[CLOSE] Could I put 15 minutes in the diary this week for a quick demo?\n"
                    "[OPT-OUT / COMPLIANCE] If now's not a good time I'm happy to remove you from our list."),
        "created_at": now_utc().isoformat(),
    })
    voice_id = "george"
    camp_id = new_id("camp")
    await db.campaigns.insert_one({
        "id": camp_id, "org_id": org_id, "name": "Q3 UK SaaS Outreach",
        "script_id": script_id, "voice_id": voice_id, "description": "Targeting UK B2B sales leaders.",
        "status": "active", "created_at": now_utc().isoformat(),
    })
    demo_contacts = [
        ("James Whitfield", "+447700900111", "Northgate Logistics", "positive", "positive", True),
        ("Priya Sharma", "+447700900222", "BrightPath Recruitment", "contacted", "neutral", True),
        ("Tom O'Brien", "+447700900333", "Apex Financial", "new", None, False),
        ("Sarah Bennett", "+447700900444", "Cloudline Media", "callback", "positive", True),
        ("Daniel Cole", "+447700900555", "Vertex Manufacturing", "opted_out", "negative", False),
        ("Aisha Khan", "+447700900666", "Riverside Health", "new", None, True),
    ]
    for name, phone, company, status, sentiment, consent in demo_contacts:
        await db.contacts.insert_one({
            "id": new_id("contact"), "org_id": org_id, "name": name, "phone": phone,
            "email": name.lower().replace(" ", ".").replace("'", "") + "@example.co.uk",
            "company": company, "notes": "", "consent": consent, "status": status,
            "opted_out": status in ("opted_out", "dnc"), "sentiment": sentiment,
            "last_called_at": now_utc().isoformat() if status != "new" else None,
            "created_at": now_utc().isoformat(),
        })
    await db.dnc_list.update_one(
        {"org_id": org_id, "phone": "+447700900555"},
        {"$setOnInsert": {"id": new_id("dnc"), "org_id": org_id, "phone": "+447700900555",
                          "reason": "opted_out_on_call", "created_at": now_utc().isoformat()}}, upsert=True)


@app.on_event("startup")
async def startup():
    await create_indexes()
    await create_messaging_indexes()
    await seed_admin()
    await seed_owner()
    await seed_demo_data()
    asyncio.create_task(email_scheduler_loop())
    logger.info("ColdWave startup complete — services healthy")


@app.on_event("shutdown")
async def shutdown():
    logger.info("ColdWave shutting down gracefully")
    db.client.close() if hasattr(db, "client") else None
