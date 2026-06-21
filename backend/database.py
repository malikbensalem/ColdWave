import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]


async def create_indexes():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("org_id")
    await db.user_sessions.create_index("session_token")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")
    await db.contacts.create_index([("org_id", 1), ("phone", 1)])
    await db.campaigns.create_index("org_id")
    await db.scripts.create_index("org_id")
    await db.calls.create_index([("org_id", 1), ("created_at", -1)])
    await db.dnc_list.create_index([("org_id", 1), ("phone", 1)], unique=True)
    await db.audit_logs.create_index([("org_id", 1), ("created_at", -1)])
    await db.kb_entries.create_index([("org_id", 1), ("created_at", -1)])
