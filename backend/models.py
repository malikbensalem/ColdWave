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
    role: str = "agent"
    password: str


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    name: Optional[str] = None


class BanRequest(BaseModel):
    reason: str


class RoleCreate(BaseModel):
    name: str
    permissions: dict = {}
    capabilities: List[str] = []
    scope: Optional[str] = None  # 'platform' (owner) or a business org_id; default = own org


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    permissions: Optional[dict] = None
    capabilities: Optional[List[str]] = None


class BlueprintCreate(BaseModel):
    name: str
    prompt: str = ""
    is_default: bool = False
    channel: str = "global"  # global | call | email | whatsapp | sms


class BlueprintUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    is_default: Optional[bool] = None
    channel: Optional[str] = None


class AssignBlueprintRequest(BaseModel):
    blueprint_id: Optional[str] = None


class AssignChannelBlueprintRequest(BaseModel):
    channel: Literal["call", "whatsapp", "sms", "email"]
    blueprint_id: Optional[str] = None


class AdminSetRoleRequest(BaseModel):
    role: str


class DialRequest(BaseModel):
    contact_id: Optional[str] = None
    destination: Optional[str] = None
    campaign_id: Optional[str] = None


class TcxTestRequest(BaseModel):
    tcx_url: Optional[str] = None
    tcx_extension: Optional[str] = None
    tcx_username: Optional[str] = None
    tcx_password: Optional[str] = None
    tcx_verify_tls: Optional[bool] = None


class TwilioTestRequest(BaseModel):
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None


class TakeoverRequest(BaseModel):
    human_number: str


# ---------- Org / Settings ----------
class IntegrationSettings(BaseModel):
    telephony_provider: str = "3cx"  # "3cx" | "twilio"
    tcx_enabled: bool = False
    tcx_url: str = ""
    tcx_username: str = ""
    tcx_password: str = ""
    tcx_extension: str = ""
    tcx_verify_tls: bool = True
    twilio_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_voice_mode: str = "stream"  # "stream" (ConversationRelay, interruptible) | "gather" (turn-based)
    elevenlabs_api_key: str = ""
    elevenlabs_enabled: bool = False
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity: float = 0.75
    elevenlabs_style: float = 0.0
    o365_enabled: bool = False
    o365_tenant_id: str = ""
    o365_client_id: str = ""
    o365_client_secret: str = ""
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""


class OrgUpdateRequest(BaseModel):
    name: Optional[str] = None
    calling_hours_start: Optional[str] = None  # "08:00"
    calling_hours_end: Optional[str] = None    # "20:00"
    calling_days: Optional[List[str]] = None   # ["mon",...]
    opening_mode: Optional[str] = None         # "scripted" | "kb"
    opening_creativity: Optional[str] = None   # "low" | "medium" | "high"
    opening_max_length: Optional[int] = None
    ai_system_prompt: Optional[str] = None     # org-level extension to the global AI prompt
    brand_name: Optional[str] = None           # white-label display name
    logo_url: Optional[str] = None             # white-label logo URL
    primary_color: Optional[str] = None        # white-label primary colour (hex)


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
    script_type: str = "line_by_line"  # "line_by_line" | "personality"
    personality: str = ""


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    objective: Optional[str] = None
    script_type: Optional[str] = None
    personality: Optional[str] = None


class GenerateScriptRequest(BaseModel):
    product: str
    audience: str
    objective: str
    tone: str = "professional and friendly"
    script_type: str = "line_by_line"
    personality: str = ""


# ---------- Campaigns ----------
class CampaignCreate(BaseModel):
    name: str
    script_id: Optional[str] = None
    voice_id: Optional[str] = None
    description: Optional[str] = ""
    audience: Literal["all", "new", "positive", "contacted", "callback", "consented", "specific"] = "all"
    contact_ids: Optional[List[str]] = None
    schedule_type: Literal["manual", "scheduled"] = "manual"
    scheduled_at: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    script_id: Optional[str] = None
    voice_id: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    audience: Optional[Literal["all", "new", "positive", "contacted", "callback", "consented", "specific"]] = None
    contact_ids: Optional[List[str]] = None
    schedule_type: Optional[Literal["manual", "scheduled"]] = None
    scheduled_at: Optional[str] = None


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


class ElevenLabsTestRequest(BaseModel):
    api_key: str = ""


class LLMTestRequest(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""


class KBToggleRequest(BaseModel):
    active: bool


# ---------- Omnichannel AI auto-reply approval ----------
class SimulateInboundRequest(BaseModel):
    sender: str
    text: str
    contact_id: Optional[str] = None
    channel: Literal["whatsapp", "sms", "email"] = "whatsapp"


class ApprovalEditRequest(BaseModel):
    draft_text: str


# ---------- Voice characteristics ----------
class VoiceCharacteristicsUpdate(BaseModel):
    name: Optional[str] = None
    persona: Optional[str] = None
    speed: Optional[float] = None      # 0.7 (slower) – 1.2 (faster); 1.0 = normal
    stability: Optional[float] = None  # 0.0 – 1.0 (ElevenLabs)
    style: Optional[float] = None      # 0.0 – 1.0 (ElevenLabs expressiveness)
    dynamic: Optional[bool] = None     # AI varies stability/style/speed by context


# ---------- Impersonation ----------
class ImpersonateRequest(BaseModel):
    user_id: Optional[str] = None
    role: Optional[str] = None
    org_id: Optional[str] = None


# ---------- Global platform settings (owner) ----------
class GlobalSettingsUpdate(BaseModel):
    ai_system_prompt: str = ""


# ---------- KB edit ----------
class KBUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


# ---------- Email integration / campaigns ----------
class EmailIntegrationUpdate(BaseModel):
    provider: Literal["gmail", "o365"]
    account_email: str = ""


class EmailCampaignCreate(BaseModel):
    name: str
    subject: str
    body: str
    schedule_type: Literal["now", "scheduled", "recurring"] = "now"
    scheduled_at: Optional[str] = None  # ISO datetime
    recurrence: Optional[Literal["daily", "weekly", "monthly"]] = None
    audience: Literal["all", "positive", "contacted", "consented"] = "all"


class EmailCampaignUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    schedule_type: Optional[Literal["now", "scheduled", "recurring"]] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[Literal["daily", "weekly", "monthly"]] = None
    audience: Optional[Literal["all", "positive", "contacted", "consented"]] = None
    status: Optional[str] = None
