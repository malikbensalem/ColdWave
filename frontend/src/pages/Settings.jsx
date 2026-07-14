import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import api, { apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { applyBranding, applyPrimaryColor } from "../lib/branding";
import RolesManager from "../components/RolesManager";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import {
  Plug, Buildings, UsersThree, BookOpen, FloppyDisk, Plus, Trash, Phone, MicrophoneStage, Brain, MicrosoftOutlookLogo, CheckCircle, Key, WhatsappLogo, Sparkle, ListMagnifyingGlass, UploadSimple, BookBookmark, PencilSimple, ShieldStar, UserSwitch, Prohibit, Palette,
} from "@phosphor-icons/react";

export default function Settings() {
  const { user, can } = useAuth();
  const showIntegrations = can("integrations", "read");
  const showUsers = can("users", "read");
  const showRoles = can("roles", "read");
  const showAudit = can("audit", "read");
  return (
    <div className="space-y-5 animate-fadeup" data-testid="settings-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Integrations, organisation, users and the credentials playbook.</p>
      </div>
      <Tabs defaultValue={showIntegrations ? "integrations" : "org"}>
        <TabsList>
          {showIntegrations && <TabsTrigger value="integrations" data-testid="tab-integrations"><Plug size={16} className="mr-1.5" />Integrations</TabsTrigger>}
          <TabsTrigger value="org" data-testid="tab-org"><Buildings size={16} className="mr-1.5" />Organisation</TabsTrigger>
          <TabsTrigger value="opening" data-testid="tab-opening"><BookBookmark size={16} className="mr-1.5" />Company Overview</TabsTrigger>
          {showIntegrations && <TabsTrigger value="whitelabel" data-testid="tab-whitelabel"><Palette size={16} className="mr-1.5" />White-label</TabsTrigger>}
          {showUsers && <TabsTrigger value="users" data-testid="tab-users"><UsersThree size={16} className="mr-1.5" />Users</TabsTrigger>}
          {showRoles && <TabsTrigger value="roles" data-testid="tab-roles"><ShieldStar size={16} className="mr-1.5" />Roles &amp; Access</TabsTrigger>}
          {showAudit && <TabsTrigger value="audit" data-testid="tab-audit"><ListMagnifyingGlass size={16} className="mr-1.5" />Audit</TabsTrigger>}
          <TabsTrigger value="playbook" data-testid="tab-playbook"><BookOpen size={16} className="mr-1.5" />Playbook</TabsTrigger>
        </TabsList>
        {showIntegrations && <TabsContent value="integrations" className="mt-4"><IntegrationsTab /></TabsContent>}
        <TabsContent value="org" className="mt-4"><OrgTab /></TabsContent>
        <TabsContent value="opening" className="mt-4"><OpeningTab /></TabsContent>
        {showIntegrations && <TabsContent value="whitelabel" className="mt-4"><WhiteLabelTab /></TabsContent>}
        {showUsers && <TabsContent value="users" className="mt-4"><UsersTab me={user} /></TabsContent>}
        {showRoles && <TabsContent value="roles" className="mt-4"><RolesManager /></TabsContent>}
        {showAudit && <TabsContent value="audit" className="mt-4"><AuditTab /></TabsContent>}
        <TabsContent value="playbook" className="mt-4"><PlaybookTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function IntegrationsTab() {
  const [data, setData] = useState(null);
  const [elevenStatus, setElevenStatus] = useState(null);
  const [elevenBusy, setElevenBusy] = useState(false);
  const [elevenModels, setElevenModels] = useState([]);
  const [llmModels, setLlmModels] = useState({});
  const [llmStatus, setLlmStatus] = useState(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const elevenTimer = useRef(null);
  const elevenLastKey = useRef(null);
  const llmTimer = useRef(null);
  const llmLastKey = useRef(null);
  const load = useCallback(async () => {
    try {
      const [r, m, em] = await Promise.all([api.get("/settings/integrations"), api.get("/llm/models"), api.get("/elevenlabs/models")]);
      setData(r.data); setLlmModels(m.data); setElevenModels(em.data.models || []);
      elevenLastKey.current = r.data.elevenlabs_api_key || "";
    } catch (e) { toast.error(apiErr(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const save = async (override) => { try { await api.put("/settings/integrations", override || data); toast.success("Integrations saved"); } catch (e) { toast.error(apiErr(e)); } };
  const testTcx = async () => {
    try {
      const r = await api.post("/settings/integrations/tcx/test", {
        tcx_url: data.tcx_url, tcx_extension: data.tcx_extension,
        tcx_username: data.tcx_username, tcx_password: data.tcx_password,
        tcx_verify_tls: data.tcx_verify_tls,
      });
      toast.success(r.data.message);
    } catch (e) { toast.error(apiErr(e)); }
  };
  const [twilioStatus, setTwilioStatus] = useState(null);
  const [twilioBusy, setTwilioBusy] = useState(false);
  const testTwilio = async () => {
    setTwilioBusy(true); setTwilioStatus(null);
    try {
      const r = await api.post("/settings/integrations/twilio/test", { account_sid: data.twilio_account_sid, auth_token: data.twilio_auth_token });
      setTwilioStatus(r.data);
      r.data.valid ? toast.success(r.data.message) : toast.error(r.data.message);
    } catch (e) { toast.error(apiErr(e)); }
    finally { setTwilioBusy(false); }
  };
  const [balances, setBalances] = useState(null);
  const [balBusy, setBalBusy] = useState(false);
  const webhookBase = (process.env.REACT_APP_BACKEND_URL || window.location.origin).replace(/\/$/, "");
  const loadBalances = async () => {
    setBalBusy(true);
    try { const r = await api.get("/settings/integrations/balances"); setBalances(r.data.balances || []); }
    catch (e) { toast.error(apiErr(e)); }
    finally { setBalBusy(false); }
  };

  const validateEleven = async (auto = false) => {
    setElevenBusy(true); setElevenStatus(null);
    try {
      const r = await api.post("/settings/integrations/elevenlabs/test", { api_key: data.elevenlabs_api_key || "" });
      setElevenStatus(r.data);
      if (r.data.valid) {
        // Auto-enable voices and persist when the key is valid.
        const next = { ...data, elevenlabs_enabled: true };
        setData(next);
        await save(next);
        toast.success(`${r.data.message} ElevenLabs voices enabled.`);
      } else if (!auto) {
        toast.error(r.data.message);
      }
    } catch (e) { if (!auto) toast.error(apiErr(e)); }
    finally { setElevenBusy(false); }
  };

  const PROVIDER_KEY = { openai: "openai_api_key", anthropic: "anthropic_api_key", gemini: "gemini_api_key" };
  const validateLlm = async (auto = false) => {
    setLlmBusy(true); setLlmStatus(null);
    try {
      const r = await api.post("/settings/integrations/llm/test", { provider: data.llm_provider, api_key: data[PROVIDER_KEY[data.llm_provider]] || "", model: data.llm_model });
      setLlmStatus(r.data);
      if (!auto) { r.data.valid ? toast.success(r.data.message) : toast.error(r.data.message); }
    } catch (e) { if (!auto) toast.error(apiErr(e)); }
    finally { setLlmBusy(false); }
  };

  // Debounced auto-validation of the ElevenLabs key on paste/change.
  useEffect(() => {
    if (!data) return;
    const key = data.elevenlabs_api_key || "";
    if (!key || key === elevenLastKey.current) return;
    if (elevenTimer.current) clearTimeout(elevenTimer.current);
    elevenTimer.current = setTimeout(() => { elevenLastKey.current = key; validateEleven(true); }, 900);
    return () => elevenTimer.current && clearTimeout(elevenTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.elevenlabs_api_key]);

  // Debounced auto-validation of the selected LLM provider key.
  useEffect(() => {
    if (!data) return;
    const key = data[PROVIDER_KEY[data.llm_provider]] || "";
    if (!key || key === llmLastKey.current) return;
    if (llmTimer.current) clearTimeout(llmTimer.current);
    llmTimer.current = setTimeout(() => { llmLastKey.current = key; validateLlm(true); }, 900);
    return () => llmTimer.current && clearTimeout(llmTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.openai_api_key, data?.anthropic_api_key, data?.gemini_api_key, data?.llm_provider]);

  const setProvider = (e) => {
    const p = e.target.value;
    const models = llmModels[p] || [];
    setData({ ...data, llm_provider: p, llm_model: models[0] || data.llm_model });
    setLlmStatus(null);
  };
  const set = (k) => (e) => setData({ ...data, [k]: e.target.type === "checkbox" ? e.target.checked : (e.target.type === "number" ? parseFloat(e.target.value) : e.target.value) });
  if (!data) return <div className="text-sm text-muted-foreground">Loading…</div>;

  return (
    <div className="space-y-4 max-w-3xl">
      <Section icon={Key} title="Credits & balances" badge={balances ? `${balances.length} connected` : "Check"}>
        <p className="text-xs text-muted-foreground -mt-1 mb-2">Live remaining credit for each connected provider.</p>
        <button data-testid="refresh-balances-button" onClick={loadBalances} disabled={balBusy}
          className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent disabled:opacity-60">
          {balBusy ? "Checking…" : "Check balances"}
        </button>
        {balances && (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="balances-grid">
            {balances.length === 0 && <p className="text-xs text-muted-foreground">No providers connected yet — add keys below.</p>}
            {balances.map((b) => (
              <div key={b.provider} data-testid={`balance-${b.provider}`} className="border border-border rounded-sm p-3 bg-card">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold">{b.label}</span>
                  <span className={`w-2 h-2 rounded-full ${b.ok ? "bg-success" : "bg-destructive"}`} />
                </div>
                {b.value != null && b.unit === "characters" && <div className="text-lg font-bold tnum mt-0.5">{Number(b.value).toLocaleString()} <span className="text-xs font-normal text-muted-foreground">chars</span></div>}
                {b.value != null && b.unit === "balance" && <div className="text-lg font-bold tnum mt-0.5">{b.value}</div>}
                <div className="text-xs text-muted-foreground mt-0.5">{b.detail}</div>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section icon={Phone} title="Telephony provider" badge={(data.telephony_provider || "3cx") === "twilio" ? "Twilio" : "3CX"}>
        <p className="text-xs text-muted-foreground -mt-1 mb-2">Choose which provider places calls (and SMS). Configure the selected one below.</p>
        <div className="inline-flex rounded-sm border border-border overflow-hidden" data-testid="telephony-provider-switch">
          {[["3cx", "3CX Call Control"], ["twilio", "Twilio"]].map(([v, label]) => (
            <button key={v} type="button" data-testid={`provider-${v}`} onClick={() => { const next = { ...data, telephony_provider: v }; setData(next); save(next); }}
              className={`h-9 px-4 text-sm font-medium ${(data.telephony_provider || "3cx") === v ? "bg-primary text-primary-foreground" : "bg-card hover:bg-accent"}`}>{label}</button>
          ))}
        </div>
      </Section>

      <Section icon={Phone} title="3CX Telephony (Call Control API)" badge={data.tcx_url ? "Configured" : "Not set"}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <F label="3CX Call Control URL" testid="tcx-url" value={data.tcx_url} onChange={set("tcx_url")} placeholder="https://yourpbx.3cx.co.za:5001" />
          <F label="Extension / DN" testid="tcx-ext" value={data.tcx_extension} onChange={set("tcx_extension")} placeholder="2089" />
          <F label="API Client ID" testid="tcx-user" value={data.tcx_username} onChange={set("tcx_username")} placeholder="Client ID from 3CX → Integrations → API" />
          <F label="API Key (secret)" testid="tcx-pass" type="password" value={data.tcx_password} onChange={set("tcx_password")} placeholder="API key shown once on creation" />
        </div>
        <div className="flex items-center gap-3 mt-1 flex-wrap">
          <Toggle testid="tcx-enabled" label="Enable 3CX live calling" checked={data.tcx_enabled} onChange={set("tcx_enabled")} />
          <Toggle testid="tcx-verify-tls" label="Verify TLS certificate" checked={data.tcx_verify_tls !== false} onChange={set("tcx_verify_tls")} />
          <button data-testid="test-tcx-button" onClick={testTcx} className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent">Test connection</button>
        </div>
        <p className="text-xs text-muted-foreground">Create an app in <b>3CX Admin → Integrations → API</b> with <b>Call Control Access</b> enabled (8SC+ Enterprise) and use its <b>Client ID</b> + <b>API Key</b>. Use the bare PBX FQDN (no <code>www.</code>). <b>For automated outbound (no human), set "Extension / DN" to a 3CX Route Point</b> assigned to this app — a normal user extension just rings itself instead of dialing out.</p>
      </Section>

      <Section icon={Phone} title="Twilio (Programmable Voice & SMS)" badge={twilioStatus ? (twilioStatus.valid ? "Valid ✓" : "Invalid ✗") : (data.twilio_account_sid ? "Key set" : "Not set")}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <F label="Account SID" testid="twilio-sid" value={data.twilio_account_sid} onChange={set("twilio_account_sid")} placeholder="AC…" />
          <F label="Auth Token" testid="twilio-token" type="password" value={data.twilio_auth_token} onChange={set("twilio_auth_token")} placeholder="Your Twilio auth token" />
          <F label="Twilio phone number" testid="twilio-number" value={data.twilio_phone_number} onChange={set("twilio_phone_number")} placeholder="+441234567890" />
        </div>
        <div className="flex items-center gap-3 mt-1 flex-wrap">
          <Toggle testid="twilio-enabled" label="Enable Twilio live calling / SMS" checked={data.twilio_enabled} onChange={set("twilio_enabled")} />
          <button data-testid="test-twilio-button" onClick={testTwilio} disabled={twilioBusy} className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent disabled:opacity-60">{twilioBusy ? "Testing…" : "Test connection"}</button>
          <button data-testid="save-twilio-button" onClick={() => save()} className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent">Save</button>
        </div>
        {twilioStatus && <p className={`text-xs ${twilioStatus.valid ? "text-success" : "text-destructive"}`}>{twilioStatus.message}</p>}
        <div className="mt-2 pt-2 border-t border-border">
          <p className="text-xs font-medium mb-1">Real-time AI voice webhook</p>
          <p className="text-xs text-muted-foreground mb-1.5">Outbound campaign calls use this streaming webhook automatically. To also answer <b>inbound</b> calls with the AI, paste this URL into the Twilio Console → your number → <b>Voice → “A call comes in” (Webhook, HTTP POST)</b>:</p>
          <div className="flex items-center gap-2">
            <code data-testid="twilio-webhook-url" className="flex-1 text-xs bg-secondary rounded-sm px-2 py-1.5 overflow-x-auto whitespace-nowrap">{webhookBase}/api/telephony/twilio/relay/incoming</code>
            <button type="button" data-testid="copy-webhook-button" onClick={() => { navigator.clipboard?.writeText(`${webhookBase}/api/telephony/twilio/relay/incoming`); toast.success("Webhook URL copied"); }}
              className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent shrink-0">Copy</button>
          </div>
          <p className="text-xs text-muted-foreground mt-1.5">⚡ <b>For sub-1s responses</b> pick a fast model (<b>GPT-4o</b> / <b>GPT-4.1-mini</b>) in the AI Language Model section below — Claude adds ~1.2s to the first word.</p>
        </div>
        <p className="text-xs text-muted-foreground">Find your <b>Account SID</b> &amp; <b>Auth Token</b> on the <b>Twilio Console dashboard</b>, and buy/verify a number under <b>Phone Numbers</b>. Select <b>Twilio</b> in “Telephony provider” above to make it the active caller.</p>
      </Section>

      <Section icon={MicrophoneStage} title="ElevenLabs Voice" badge={elevenStatus ? (elevenStatus.valid ? "Valid ✓" : "Invalid ✗") : (data.elevenlabs_api_key ? "Key set" : "Mock mode")}>
        <F label="API Key (auto-validates on paste)" testid="eleven-key" type="password" value={data.elevenlabs_api_key} onChange={set("elevenlabs_api_key")} placeholder="sk-..." />
        <div className="flex items-center gap-3">
          <Toggle testid="eleven-enabled" label="Use ElevenLabs for voice synthesis" checked={data.elevenlabs_enabled} onChange={set("elevenlabs_enabled")} />
          {elevenBusy && <span className="text-xs text-muted-foreground">Validating…</span>}
          <button data-testid="validate-eleven-button" onClick={() => validateEleven(false)} disabled={elevenBusy} className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent disabled:opacity-60">{elevenBusy ? "Checking…" : "Validate key"}</button>
        </div>
        {elevenStatus && (
          <div data-testid="eleven-validate-result" className={`text-xs rounded-sm p-2 border ${elevenStatus.valid ? "border-success/40 bg-success/10 text-success" : "border-destructive/40 bg-destructive/10 text-destructive"}`}>{elevenStatus.message}</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Sel label="Model" testid="eleven-model" value={data.elevenlabs_model || "eleven_multilingual_v2"} onChange={set("elevenlabs_model")} options={elevenModels.map((m) => ({ value: m, label: m }))} />
        </div>
        <p className="text-xs text-muted-foreground">Paste a key and it validates automatically — if valid, voices are enabled and saved. Test calls then use ElevenLabs audio (no silent fallback).</p>
      </Section>

      <Section icon={WhatsappLogo} title="WhatsApp Business Cloud API" badge={data.whatsapp_access_token ? "Configured" : "Mock mode"}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <F label="Phone Number ID" testid="wa-phone-id" value={data.whatsapp_phone_number_id || ""} onChange={set("whatsapp_phone_number_id")} />
          <F label="Business Account ID" testid="wa-business-id" value={data.whatsapp_business_account_id || ""} onChange={set("whatsapp_business_account_id")} />
          <F label="Access Token" testid="wa-token" type="password" value={data.whatsapp_access_token || ""} onChange={set("whatsapp_access_token")} />
          <F label="App Secret (webhook signing)" testid="wa-secret" type="password" value={data.whatsapp_app_secret || ""} onChange={set("whatsapp_app_secret")} />
        </div>
        <Toggle testid="wa-enabled" label="Enable WhatsApp live sending" checked={data.whatsapp_enabled} onChange={set("whatsapp_enabled")} />
        <p className="text-xs text-muted-foreground">From Meta → WhatsApp → API Setup. Webhook URL: <code className="text-foreground">{`{backend}/api/webhooks/whatsapp`}</code>. Without credentials, WhatsApp runs in safe mock mode.</p>
      </Section>

      <Section icon={Brain} title="AI Language Model" badge={llmStatus ? (llmStatus.valid ? "Valid ✓" : "Check key") : (data[PROVIDER_KEY[data.llm_provider]] ? "Custom key" : "Emergent key")}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Sel label="Provider" testid="llm-provider" value={data.llm_provider} onChange={setProvider} options={[{ value: "anthropic", label: "Anthropic (Claude)" }, { value: "openai", label: "OpenAI" }, { value: "gemini", label: "Google Gemini" }]} />
          <Sel label="Model" testid="llm-model" value={data.llm_model} onChange={set("llm_model")} options={(llmModels[data.llm_provider] || []).map((m) => ({ value: m, label: m }))} />
        </div>
        <F label={`${data.llm_provider} API key (auto-validates on paste — leave blank to use the Emergent key)`} testid="llm-key" type="password"
          value={data[PROVIDER_KEY[data.llm_provider]] || ""} onChange={set(PROVIDER_KEY[data.llm_provider])} placeholder="Bring your own key for the selected provider…" />
        <div className="flex items-center gap-3">
          {llmBusy && <span className="text-xs text-muted-foreground">Validating…</span>}
          <button data-testid="validate-llm-button" onClick={() => validateLlm(false)} disabled={llmBusy} className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent disabled:opacity-60">{llmBusy ? "Checking…" : "Validate key"}</button>
          {llmStatus && <span data-testid="llm-validate-result" className={`text-xs ${llmStatus.valid ? "text-success" : "text-destructive"}`}>{llmStatus.message}</span>}
        </div>
        <div className="text-xs text-muted-foreground border-t border-border pt-2 mt-1">
          <div className="font-semibold mb-1 text-foreground">Saved provider keys (what you save is exactly what's shown):</div>
          <div className="flex flex-wrap gap-2">
            {["openai", "anthropic", "gemini"].map((p) => (
              <span key={p} data-testid={`llm-key-status-${p}`} className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm border ${data[PROVIDER_KEY[p]] ? "border-success/40 bg-success/10 text-success" : "border-border"}`}>
                <span className="capitalize">{p}</span>{data[PROVIDER_KEY[p]] ? "set" : "—"}
                {data[PROVIDER_KEY[p]] && <button type="button" data-testid={`llm-key-clear-${p}`} onClick={() => setData({ ...data, [PROVIDER_KEY[p]]: "" })} className="ml-0.5 hover:text-destructive">✕</button>}
              </span>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">Powers scripts, live test-call conversation, and transcript analysis. Add your own provider key to use your account; otherwise the Emergent Universal key is used.</p>
      </Section>

      <Section icon={MicrosoftOutlookLogo} title="Office 365 SSO (Azure AD)" badge={data.o365_enabled ? "Enabled" : "Disabled"}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <F label="Tenant ID" testid="o365-tenant" value={data.o365_tenant_id} onChange={set("o365_tenant_id")} />
          <F label="Client ID" testid="o365-client" value={data.o365_client_id} onChange={set("o365_client_id")} />
          <F label="Client Secret" testid="o365-secret" type="password" value={data.o365_client_secret} onChange={set("o365_client_secret")} />
        </div>
        <Toggle testid="o365-enabled" label="Enable Office 365 SSO for this workspace" checked={data.o365_enabled} onChange={set("o365_enabled")} />
      </Section>

      <button data-testid="save-integrations-button" onClick={() => save()} className="inline-flex items-center gap-2 h-10 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><FloppyDisk size={16} weight="bold" /> Save Integrations</button>
    </div>
  );
}

function OrgTab() {
  const [org, setOrg] = useState(null);
  const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const load = useCallback(async () => { const r = await api.get("/settings/org"); setOrg(r.data); }, []);
  useEffect(() => { load(); }, [load]);
  const save = async () => { try { await api.put("/settings/org", { name: org.name, calling_hours_start: org.calling_hours_start, calling_hours_end: org.calling_hours_end, calling_days: org.calling_days}); toast.success("Saved"); } catch (e) { toast.error(apiErr(e)); } };
  if (!org) return <div className="text-sm text-muted-foreground">Loading…</div>;
  const toggleDay = (d) => setOrg({ ...org, calling_days: org.calling_days.includes(d) ? org.calling_days.filter((x) => x !== d) : [...org.calling_days, d] });
  return (
    <div className="space-y-4 max-w-xl">
      <Section icon={Buildings} title="Organisation">
        <F label="Workspace name" testid="org-name-input" value={org.name} onChange={(e) => setOrg({ ...org, name: e.target.value })} />
      </Section>
      <Section icon={Phone} title="UK Calling Hours">
        <div className="grid grid-cols-2 gap-3">
          <F label="Start" testid="hours-start" type="time" value={org.calling_hours_start} onChange={(e) => setOrg({ ...org, calling_hours_start: e.target.value })} />
          <F label="End" testid="hours-end" type="time" value={org.calling_hours_end} onChange={(e) => setOrg({ ...org, calling_hours_end: e.target.value })} />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {DAYS.map((d) => (
            <button key={d} data-testid={`day-${d}`} onClick={() => toggleDay(d)} className={`px-3 h-9 rounded-sm text-xs font-semibold uppercase border ${org.calling_days.includes(d) ? "bg-primary text-primary-foreground border-primary" : "bg-card border-border text-muted-foreground"}`}>{d}</button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">Outbound calls are blocked outside these hours/days (UK PECR good practice).</p>
      </Section>
      <button data-testid="save-org-button" onClick={save} className="inline-flex items-center gap-2 h-10 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><FloppyDisk size={16} weight="bold" /> Save</button>
    </div>
  );
}

function WhiteLabelTab() {
  const [org, setOrg] = useState(null);
  const load = useCallback(async () => { const r = await api.get("/settings/org"); setOrg(r.data); }, []);
  useEffect(() => { load(); }, [load]);
  const save = async () => {
    try {
      await api.put("/settings/org", { brand_name: org.brand_name || "", logo_url: org.logo_url || "", primary_color: org.primary_color || "" });
      const r = await api.get("/settings/branding");
      applyBranding(r.data);
      toast.success("Branding saved — applied across the app.");
    } catch (e) { toast.error(apiErr(e)); }
  };
  const reset = async () => {
    try {
      await api.put("/settings/org", { brand_name: "", logo_url: "", primary_color: "" });
      applyPrimaryColor(null);
      applyBranding({ brand_name: "", logo_url: "", primary_color: "" });
      setOrg({ ...org, brand_name: "", logo_url: "", primary_color: "" });
      toast.success("Reverted to ColdWave defaults.");
    } catch (e) { toast.error(apiErr(e)); }
  };
  if (!org) return <div className="text-sm text-muted-foreground">Loading…</div>;
  const color = org.primary_color || "#1d4ed8";
  return (
    <div className="space-y-4 max-w-xl">
      <Section icon={Palette} title="White-label branding">
        <p className="text-xs text-muted-foreground -mt-1 mb-1">Customise the workspace name, logo and primary colour. A subtle “Powered by ColdWave” credit is always retained.</p>
        <F label="Brand / company name" testid="brand-name-input" value={org.brand_name || ""} onChange={(e) => setOrg({ ...org, brand_name: e.target.value })} placeholder="e.g. Acme Outreach" />
        <F label="Logo URL" testid="brand-logo-input" value={org.logo_url || ""} onChange={(e) => setOrg({ ...org, logo_url: e.target.value })} placeholder="https://…/logo.png" />
        <div>
          <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Primary colour</label>
          <div className="mt-1 flex items-center gap-3">
            <input type="color" data-testid="brand-color-input" value={color} onChange={(e) => setOrg({ ...org, primary_color: e.target.value })}
              className="h-10 w-14 rounded-sm border border-input bg-card cursor-pointer" />
            <span className="text-sm tnum text-muted-foreground">{color}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 mt-2 p-3 rounded-sm border border-border bg-card" data-testid="brand-preview">
          {org.logo_url ? <img src={org.logo_url} alt="logo" className="h-8 w-8 rounded-sm object-cover" /> : <div className="h-8 w-8 rounded-sm flex items-center justify-center text-white font-bold" style={{ backgroundColor: color }}>A</div>}
          <div>
            <div className="font-display font-bold">{org.brand_name || "ColdWave"}</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">AI Calling</div>
          </div>
          <button type="button" className="ml-auto h-8 px-3 rounded-sm text-xs font-semibold text-white" style={{ backgroundColor: color }}>Sample button</button>
        </div>
      </Section>
      <div className="flex gap-2">
        <button data-testid="save-brand-button" onClick={save} className="inline-flex items-center gap-2 h-10 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><FloppyDisk size={16} weight="bold" /> Save branding</button>
        <button data-testid="reset-brand-button" onClick={reset} className="h-10 px-4 rounded-sm border border-border text-sm font-medium hover:bg-accent">Reset to ColdWave</button>
      </div>
    </div>
  );
}

function UsersTab({ me }) {
  const { hasCap, can, impersonate } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "agent" });
  const [banUser, setBanUser] = useState(null);
  const [banReason, setBanReason] = useState("");
  const canCreate = can("users", "create");
  const canDelete = can("users", "delete");
  const canBan = hasCap("ban_users");
  const canImpersonate = hasCap("impersonate_users");
  const load = useCallback(async () => {
    try {
      const [u, r] = await Promise.all([api.get("/users"), api.get("/roles")]);
      setUsers(u.data); setRoles(r.data.filter((x) => x.name !== "owner"));
    } catch (e) { toast.error(apiErr(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const invite = async (e) => { e.preventDefault(); try { await api.post("/users", form); toast.success("User added"); setOpen(false); setForm({ name: "", email: "", password: "", role: "agent" }); load(); } catch (err) { toast.error(apiErr(err)); } };
  const changeRole = async (u, role) => { try { await api.put(`/users/${u.id}`, { role }); load(); } catch (e) { toast.error(apiErr(e)); } };
  const remove = async (id) => { try { await api.delete(`/users/${id}`); load(); } catch (e) { toast.error(apiErr(e)); } };
  const doBan = async () => { if (!banReason.trim()) { toast.error("A reason is required to ban."); return; } try { await api.post(`/users/${banUser.id}/ban`, { reason: banReason }); toast.success("User banned"); setBanUser(null); setBanReason(""); load(); } catch (e) { toast.error(apiErr(e)); } };
  const unban = async (u) => { try { await api.post(`/users/${u.id}/unban`); toast.success("User unbanned"); load(); } catch (e) { toast.error(apiErr(e)); } };
  const doImpersonate = async (u) => { try { await impersonate(u.id); toast.success(`Now impersonating ${u.name}`); navigate("/dashboard"); } catch (e) { toast.error(apiErr(e)); } };

  return (
    <div className="space-y-3 max-w-3xl">
      <div className="flex justify-end">
        {canCreate && <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild><button data-testid="invite-user-button" className="inline-flex items-center gap-2 h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><Plus size={16} weight="bold" /> Add User</button></DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle className="font-display">Add Team Member</DialogTitle></DialogHeader>
            <form onSubmit={invite} className="space-y-3">
              <F label="Name" testid="invite-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <F label="Email" testid="invite-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
              <F label="Temporary password" testid="invite-password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
              <Sel label="Role" testid="invite-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} options={roles.map((r) => ({ value: r.name, label: r.name }))} />
              <DialogFooter><button data-testid="save-user-button" type="submit" className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Add</button></DialogFooter>
            </form>
          </DialogContent>
        </Dialog>}
      </div>
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50"><th className="py-2.5 px-4 font-semibold">Name</th><th className="py-2.5 px-4 font-semibold">Email</th><th className="py-2.5 px-4 font-semibold">Role</th><th className="py-2.5 px-4 font-semibold text-right">Actions</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-border/60 hover:bg-muted/50">
                <td className="py-2.5 px-4 font-medium">{u.name}{u.banned && <span className="ml-2 text-[10px] uppercase px-1.5 py-0.5 bg-destructive/15 text-destructive rounded-sm">Banned</span>}</td>
                <td className="py-2.5 px-4 text-muted-foreground">{u.email}</td>
                <td className="py-2.5 px-4">
                  {u.id !== me?.id && u.role !== "owner" && can("users", "update") ? (
                    <select data-testid={`role-select-${u.id}`} value={u.role} onChange={(e) => changeRole(u, e.target.value)} className="h-7 rounded-sm border border-input bg-card px-2 text-xs capitalize">
                      {roles.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
                    </select>
                  ) : <span className="text-xs px-2 py-0.5 rounded-sm font-semibold capitalize bg-muted text-muted-foreground">{u.role}</span>}
                </td>
                <td className="py-2.5 px-4 text-right space-x-2 whitespace-nowrap">
                  {canImpersonate && u.id !== me?.id && u.role !== "owner" && !u.banned && <button data-testid={`impersonate-user-${u.id}`} onClick={() => doImpersonate(u)} className="text-xs text-primary hover:underline"><UserSwitch size={13} className="inline" /> Impersonate</button>}
                  {canBan && u.id !== me?.id && u.role !== "owner" && (u.banned
                    ? <button data-testid={`unban-user-${u.id}`} onClick={() => unban(u)} className="text-xs text-success hover:underline">Unban</button>
                    : <button data-testid={`ban-user-${u.id}`} onClick={() => { setBanUser(u); setBanReason(""); }} className="text-xs text-destructive hover:underline"><Prohibit size={13} className="inline" /> Ban</button>)}
                  {canDelete && u.id !== me?.id && <button data-testid={`delete-user-${u.id}`} onClick={() => remove(u.id)} className="text-muted-foreground hover:text-destructive"><Trash size={15} /></button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Dialog open={!!banUser} onOpenChange={(o) => !o && setBanUser(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">Ban {banUser?.name}</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Reason (required)</label>
            <textarea data-testid="ban-reason-input" value={banReason} onChange={(e) => setBanReason(e.target.value)} rows={3} className="w-full rounded-sm border border-input bg-card p-2.5 text-sm" placeholder="Why is this user being banned?" />
          </div>
          <DialogFooter><button data-testid="confirm-ban-button" onClick={doBan} className="h-10 px-4 bg-destructive text-destructive-foreground rounded-sm text-sm font-medium">Ban user</button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PlaybookTab() {
  const items = [
    { icon: MicrophoneStage, name: "ElevenLabs", where: "elevenlabs.io → Settings → API Keys", env: "Paste in Integrations → ElevenLabs", note: "Realistic male/female voice synthesis." },
    { icon: Phone, name: "3CX Call Control", where: "3CX Admin Console → Integrations / API", env: "Integrations → 3CX (URL, ext, user, pass)", note: "Place & control live outbound calls." },
    { icon: MicrosoftOutlookLogo, name: "Office 365 SSO", where: "Azure Portal → App registrations", env: "Integrations → Office 365 (tenant, client, secret)", note: "Enterprise single sign-on." },
    { icon: Brain, name: "LLM (Claude)", where: "Provided via Emergent Universal Key", env: "Pre-configured", note: "Scripts, conversation, transcript analysis." },
    { icon: Key, name: "Google Login", where: "Managed by Emergent", env: "Works out of the box", note: "Social sign-in on the login screen." },
  ];
  return (
    <div className="space-y-3 max-w-3xl">
      <p className="text-sm text-muted-foreground">Where to obtain each credential and where it goes in ColdWave.</p>
      {items.map((i) => (
        <div key={i.name} className="bg-card border border-border rounded-sm p-4 flex gap-3">
          <div className="h-9 w-9 rounded-sm bg-primary/10 text-primary flex items-center justify-center flex-shrink-0"><i.icon size={18} weight="bold" /></div>
          <div className="flex-1">
            <div className="flex items-center gap-2"><span className="font-display font-semibold">{i.name}</span><CheckCircle size={15} weight="fill" className="text-success" /></div>
            <div className="text-sm text-muted-foreground mt-0.5">{i.note}</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2 text-xs">
              <div className="bg-accent rounded-sm p-2"><span className="font-semibold">Get it from:</span> {i.where}</div>
              <div className="bg-accent rounded-sm p-2"><span className="font-semibold">Configure at:</span> {i.env}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function OpeningTab() {
  const [kb, setKb] = useState([]);
  const [entry, setEntry] = useState({ title: "", content: "" });
  const [editing, setEditing] = useState(null); // {id,title,content}
  const [viewing, setViewing] = useState(null);
  const load = useCallback(async () => { const k = await api.get("/kb"); setKb(k.data); }, []);
  useEffect(() => { load(); }, [load]);
  const addEntry = async () => { if (!entry.title || !entry.content) return; try { await api.post("/kb", entry); setEntry({ title: "", content: "" }); load(); toast.success("Document added"); } catch (e) { toast.error(apiErr(e)); } };
  const upload = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try { await api.post("/kb/upload", fd, { headers: { "Content-Type": "multipart/form-data" } }); load(); toast.success("Document added"); } catch (err) { toast.error(apiErr(err)); }
    e.target.value = "";
  };
  const remove = async (id) => { await api.delete(`/kb/${id}`); load(); };
  const toggle = async (id) => { await api.put(`/kb/${id}/toggle`); load(); };
  const saveEdit = async () => {
    try { await api.put(`/kb/${editing.id}`, { title: editing.title, content: editing.content }); toast.success("Document updated"); setEditing(null); load(); }
    catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Section icon={BookBookmark} title="Add a company document">
        <div className="flex items-center gap-2">
          <label data-testid="kb-upload-label" className="inline-flex items-center gap-1.5 h-9 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent cursor-pointer">
            <UploadSimple size={15} weight="bold" /> Upload .pdf / .txt
            <input data-testid="kb-upload" type="file" accept=".pdf,.txt,.md" onChange={upload} className="hidden" />
          </label>
          <span className="text-xs text-muted-foreground">{kb.filter((k) => k.active !== false).length}/{kb.length} active</span>
        </div>
        <div className="space-y-2">
          <F label="Title" testid="kb-title" value={entry.title} onChange={(e) => setEntry({ ...entry, title: e.target.value })} />
          <textarea data-testid="kb-content" value={entry.content} onChange={(e) => setEntry({ ...entry, content: e.target.value })} rows={4} placeholder="Paste company info, products, FAQs, pricing…"
            className="w-full rounded-sm border border-input bg-card p-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          <button data-testid="kb-add" onClick={addEntry} className="inline-flex items-center gap-1.5 h-9 px-3 bg-foreground text-background rounded-sm text-sm font-medium"><Plus size={15} weight="bold" /> Add document</button>
        </div>
        <p className="text-xs text-muted-foreground">Active documents feed the live AI agent so it can talk about your company and answer off-script questions during calls.</p>
      </Section>

      <Section icon={BookBookmark} title="Company Overview Documents">
        {kb.length === 0 && <div className="text-sm text-muted-foreground py-6 text-center border border-dashed border-border rounded-sm">No documents yet — add one on the left.</div>}
        <div className="max-h-[28rem] overflow-y-auto space-y-1.5">
          {kb.map((k) => {
            const active = k.active !== false;
            return (
              <div key={k.id} data-testid={`kb-item-${k.id}`} className={`border rounded-sm px-3 py-2 ${active ? "border-success/40 bg-success/5" : "border-border opacity-70"}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0"><div className="text-sm font-medium truncate">{k.title}</div><div className="text-xs text-muted-foreground capitalize">{k.source} · {active ? "active" : "disabled"} · {(k.content || "").length} chars</div></div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button data-testid={`kb-view-${k.id}`} onClick={() => setViewing(k)} className="text-xs font-semibold px-2 h-7 rounded-sm border border-border text-muted-foreground hover:bg-accent">View</button>
                    <button data-testid={`kb-edit-${k.id}`} onClick={() => setEditing({ id: k.id, title: k.title, content: k.content || "" })} className="text-muted-foreground hover:text-primary"><PencilSimple size={15} /></button>
                    <button data-testid={`kb-toggle-${k.id}`} onClick={() => toggle(k.id)} className={`text-xs font-semibold px-2 h-7 rounded-sm border ${active ? "border-success/40 text-success" : "border-border text-muted-foreground"}`}>{active ? "Active" : "Disabled"}</button>
                    <button data-testid={`kb-delete-${k.id}`} onClick={() => remove(k.id)} className="text-muted-foreground hover:text-destructive"><Trash size={14} /></button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      <Dialog open={!!viewing} onOpenChange={(o) => !o && setViewing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle className="font-display" data-testid="kb-view-title">{viewing?.title}</DialogTitle></DialogHeader>
          <pre data-testid="kb-view-content" className="text-xs whitespace-pre-wrap max-h-[60vh] overflow-y-auto bg-accent rounded-sm p-3 font-mono">{viewing?.content}</pre>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle className="font-display">Edit document</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-3">
              <F label="Title" testid="kb-edit-title" value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
              <textarea data-testid="kb-edit-content" value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })} rows={12}
                className="w-full rounded-sm border border-input bg-card p-2.5 text-xs font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
            </div>
          )}
          <DialogFooter><button data-testid="kb-save-edit" onClick={saveEdit} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Save changes</button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AuditTab() {
  const [logs, setLogs] = useState([]);
  const [filters, setFilters] = useState({ actor: "", entity: "", action: "", date_from: "", date_to: "" });
  const load = useCallback(async () => {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v));
    try { const r = await api.get("/audit", { params }); setLogs(r.data); } catch (e) { toast.error(apiErr(e)); }
  }, [filters]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="space-y-3">
      <div className="flex gap-2 flex-wrap">
        <input data-testid="audit-actor" value={filters.actor} onChange={(e) => setFilters({ ...filters, actor: e.target.value })} placeholder="Actor email" className="h-9 px-3 rounded-sm border border-input bg-card text-sm" />
        <input data-testid="audit-entity" value={filters.entity} onChange={(e) => setFilters({ ...filters, entity: e.target.value })} placeholder="Entity (contact, message…)" className="h-9 px-3 rounded-sm border border-input bg-card text-sm" />
        <input data-testid="audit-from" type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} className="h-9 px-3 rounded-sm border border-input bg-card text-sm" />
        <input data-testid="audit-to" type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} className="h-9 px-3 rounded-sm border border-input bg-card text-sm" />
      </div>
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50">
            <th className="py-2.5 px-3 font-semibold">Time (UTC)</th><th className="py-2.5 px-3 font-semibold">Actor</th><th className="py-2.5 px-3 font-semibold">Action</th><th className="py-2.5 px-3 font-semibold">Entity</th><th className="py-2.5 px-3 font-semibold">IP</th><th className="py-2.5 px-3 font-semibold">Correlation</th></tr></thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.id} data-testid={`audit-row-${l.id}`} className="border-b border-border/60 hover:bg-muted/50">
                <td className="py-2 px-3 text-xs tnum">{(l.created_at || "").slice(0, 19).replace("T", " ")}</td>
                <td className="py-2 px-3 text-xs">{l.actor}</td>
                <td className="py-2 px-3"><span className="text-xs px-1.5 py-0.5 bg-accent rounded-sm font-medium">{l.action}</span></td>
                <td className="py-2 px-3 text-xs">{l.entity}{l.entity_id ? `:${l.entity_id.slice(0, 10)}` : ""}</td>
                <td className="py-2 px-3 text-xs tnum">{l.ip}</td>
                <td className="py-2 px-3 text-xs tnum text-muted-foreground">{(l.correlation_id || "").slice(0, 12)}</td>
              </tr>
            ))}
            {logs.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-muted-foreground text-sm">No audit entries match.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, badge, children }) {
  return (
    <div className="bg-card border border-border rounded-sm p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-display font-semibold"><Icon size={18} weight="bold" className="text-primary" /> {title}</div>
        {badge && <span className="text-xs px-2 py-0.5 bg-accent rounded-sm font-medium">{badge}</span>}
      </div>
      {children}
    </div>
  );
}
function F({ label, testid, type = "text", ...rest }) {
  return <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label><input data-testid={testid} type={type} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>;
}
function Sel({ label, testid, options, ...rest }) {
  return <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label><select data-testid={testid} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>;
}
function Toggle({ label, testid, checked, onChange }) {
  return <label className="flex items-center gap-2 text-sm cursor-pointer"><input type="checkbox" data-testid={testid} checked={checked} onChange={onChange} className="h-4 w-4" />{label}</label>;
}
