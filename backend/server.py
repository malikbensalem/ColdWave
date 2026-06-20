import os
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from database import db, create_indexes
from auth import auth_router, seed_admin
from routes import router as app_router
from models import now_utc, new_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="ColdWave AI Calling Platform")


@app.get("/api/")
async def root():
    return {"message": "ColdWave AI Calling API", "status": "ok"}


app.include_router(auth_router)
app.include_router(app_router)

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
    await seed_admin()
    await seed_demo_data()
    logger.info("ColdWave startup complete")


@app.on_event("shutdown")
async def shutdown():
    pass
