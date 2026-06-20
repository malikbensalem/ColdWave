import uuid
from datetime import datetime, timezone
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    org_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteUserRequest(BaseModel):
    email: EmailStr
    name: str
    role: Literal["admin", "agent"] = "agent"
    password: str


class UpdateUserRequest(BaseModel):
    role: Optional[Literal["admin", "agent"]] = None
    name: Optional[str] = None


# ---------- Org / Settings ----------
class IntegrationSettings(BaseModel):
    tcx_enabled: bool = False
    tcx_url: str = ""
    tcx_username: str = ""
    tcx_password: str = ""
    tcx_extension: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_enabled: bool = False
    o365_enabled: bool = False
    o365_tenant_id: str = ""
    o365_client_id: str = ""
    o365_client_secret: str = ""
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"


class OrgUpdateRequest(BaseModel):
    name: Optional[str] = None
    calling_hours_start: Optional[str] = None  # "08:00"
    calling_hours_end: Optional[str] = None    # "20:00"
    calling_days: Optional[List[str]] = None   # ["mon",...]


# ---------- CRM ----------
class ContactCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = ""
    company: Optional[str] = ""
    notes: Optional[str] = ""
    consent: bool = False


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    consent: Optional[bool] = None


# ---------- Scripts ----------
class ScriptCreate(BaseModel):
    name: str
    content: str = ""
    objective: str = ""


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    objective: Optional[str] = None


class GenerateScriptRequest(BaseModel):
    product: str
    audience: str
    objective: str
    tone: str = "professional and friendly"


# ---------- Campaigns ----------
class CampaignCreate(BaseModel):
    name: str
    script_id: Optional[str] = None
    voice_id: Optional[str] = None
    description: Optional[str] = ""


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    script_id: Optional[str] = None
    voice_id: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


# ---------- Voice ----------
class VoicePreviewRequest(BaseModel):
    voice_id: str
    text: str


# ---------- Test calls ----------
class TestCallStartRequest(BaseModel):
    campaign_id: Optional[str] = None
    script_id: Optional[str] = None
    voice_id: Optional[str] = None
    contact_id: Optional[str] = None


class TestCallTurnRequest(BaseModel):
    call_id: str
    message: str


# ---------- Compliance ----------
class DNCAddRequest(BaseModel):
    phone: str
    reason: str = "manual"


class ErasureRequest(BaseModel):
    contact_id: str
