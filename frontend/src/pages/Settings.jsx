import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import {
  Plug, Buildings, UsersThree, BookOpen, FloppyDisk, Plus, Trash, Phone, MicrophoneStage, Brain, MicrosoftOutlookLogo, CheckCircle, Key,
} from "@phosphor-icons/react";

export default function Settings() {
  const { user } = useAuth();
  return (
    <div className="space-y-5 animate-fadeup" data-testid="settings-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Integrations, organisation, users and the credentials playbook.</p>
      </div>
      {user?.role !== "admin" && <div className="text-sm bg-warning/15 border border-warning/40 text-warning-foreground rounded-sm p-3">Some settings require an admin role.</div>}
      <Tabs defaultValue="integrations">
        <TabsList>
          <TabsTrigger value="integrations" data-testid="tab-integrations"><Plug size={16} className="mr-1.5" />Integrations</TabsTrigger>
          <TabsTrigger value="org" data-testid="tab-org"><Buildings size={16} className="mr-1.5" />Organisation</TabsTrigger>
          <TabsTrigger value="users" data-testid="tab-users"><UsersThree size={16} className="mr-1.5" />Users</TabsTrigger>
          <TabsTrigger value="playbook" data-testid="tab-playbook"><BookOpen size={16} className="mr-1.5" />Playbook</TabsTrigger>
        </TabsList>
        <TabsContent value="integrations" className="mt-4"><IntegrationsTab /></TabsContent>
        <TabsContent value="org" className="mt-4"><OrgTab /></TabsContent>
        <TabsContent value="users" className="mt-4"><UsersTab me={user} /></TabsContent>
        <TabsContent value="playbook" className="mt-4"><PlaybookTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function IntegrationsTab() {
  const [data, setData] = useState(null);
  const load = useCallback(async () => { try { const r = await api.get("/settings/integrations"); setData(r.data); } catch (e) { toast.error(apiErr(e)); } }, []);
  useEffect(() => { load(); }, [load]);
  const save = async () => { try { await api.put("/settings/integrations", data); toast.success("Integrations saved"); } catch (e) { toast.error(apiErr(e)); } };
  const testTcx = async () => { try { const r = await api.post("/settings/integrations/tcx/test"); toast.success(r.data.message); } catch (e) { toast.error(apiErr(e)); } };
  const set = (k) => (e) => setData({ ...data, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  if (!data) return <div className="text-sm text-muted-foreground">Loading…</div>;

  return (
    <div className="space-y-4 max-w-3xl">
      <Section icon={Phone} title="3CX Telephony" badge={data.tcx_url ? "Configured" : "Not set"}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <F label="3CX Call Control URL" testid="tcx-url" value={data.tcx_url} onChange={set("tcx_url")} placeholder="https://yourpbx.3cx.eu:5001" />
          <F label="Extension" testid="tcx-ext" value={data.tcx_extension} onChange={set("tcx_extension")} />
          <F label="API Username" testid="tcx-user" value={data.tcx_username} onChange={set("tcx_username")} />
          <F label="API Password" testid="tcx-pass" type="password" value={data.tcx_password} onChange={set("tcx_password")} />
        </div>
        <div className="flex items-center gap-3 mt-1">
          <Toggle testid="tcx-enabled" label="Enable 3CX live calling" checked={data.tcx_enabled} onChange={set("tcx_enabled")} />
          <button data-testid="test-tcx-button" onClick={testTcx} className="h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent">Test connection</button>
        </div>
        <p className="text-xs text-muted-foreground">Live calls route through your 3CX Call Control API. Currently mock until a reachable PBX is connected.</p>
      </Section>

      <Section icon={MicrophoneStage} title="ElevenLabs Voice" badge={data.elevenlabs_api_key ? "Active" : "Mock mode"}>
        <F label="API Key" testid="eleven-key" type="password" value={data.elevenlabs_api_key} onChange={set("elevenlabs_api_key")} placeholder="sk-..." />
        <Toggle testid="eleven-enabled" label="Use ElevenLabs for voice synthesis" checked={data.elevenlabs_enabled} onChange={set("elevenlabs_enabled")} />
        <p className="text-xs text-muted-foreground">Get a key at elevenlabs.io → Settings → API Keys. Without it, previews use the browser voice.</p>
      </Section>

      <Section icon={Brain} title="AI Language Model" badge="Emergent Key">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Sel label="Provider" testid="llm-provider" value={data.llm_provider} onChange={set("llm_provider")} options={[{ value: "anthropic", label: "Anthropic" }, { value: "openai", label: "OpenAI" }, { value: "gemini", label: "Gemini" }]} />
          <F label="Model" testid="llm-model" value={data.llm_model} onChange={set("llm_model")} />
        </div>
        <p className="text-xs text-muted-foreground">Script writing, test-call conversation and transcript analysis. Default: Claude Sonnet 4.6 via the Emergent Universal key.</p>
      </Section>

      <Section icon={MicrosoftOutlookLogo} title="Office 365 SSO (Azure AD)" badge={data.o365_enabled ? "Enabled" : "Disabled"}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <F label="Tenant ID" testid="o365-tenant" value={data.o365_tenant_id} onChange={set("o365_tenant_id")} />
          <F label="Client ID" testid="o365-client" value={data.o365_client_id} onChange={set("o365_client_id")} />
          <F label="Client Secret" testid="o365-secret" type="password" value={data.o365_client_secret} onChange={set("o365_client_secret")} />
        </div>
        <Toggle testid="o365-enabled" label="Enable Office 365 SSO for this workspace" checked={data.o365_enabled} onChange={set("o365_enabled")} />
      </Section>

      <button data-testid="save-integrations-button" onClick={save} className="inline-flex items-center gap-2 h-10 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><FloppyDisk size={16} weight="bold" /> Save Integrations</button>
    </div>
  );
}

function OrgTab() {
  const [org, setOrg] = useState(null);
  const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const load = useCallback(async () => { const r = await api.get("/settings/org"); setOrg(r.data); }, []);
  useEffect(() => { load(); }, [load]);
  const save = async () => { try { await api.put("/settings/org", { name: org.name, calling_hours_start: org.calling_hours_start, calling_hours_end: org.calling_hours_end, calling_days: org.calling_days }); toast.success("Saved"); } catch (e) { toast.error(apiErr(e)); } };
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

function UsersTab({ me }) {
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "agent" });
  const load = useCallback(async () => { try { const r = await api.get("/users"); setUsers(r.data); } catch (e) { toast.error(apiErr(e)); } }, []);
  useEffect(() => { load(); }, [load]);
  const invite = async (e) => { e.preventDefault(); try { await api.post("/users", form); toast.success("User added"); setOpen(false); setForm({ name: "", email: "", password: "", role: "agent" }); load(); } catch (err) { toast.error(apiErr(err)); } };
  const changeRole = async (u) => { await api.put(`/users/${u.id}`, { role: u.role === "admin" ? "agent" : "admin" }); load(); };
  const remove = async (id) => { try { await api.delete(`/users/${id}`); load(); } catch (e) { toast.error(apiErr(e)); } };
  return (
    <div className="space-y-3 max-w-2xl">
      <div className="flex justify-end">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild><button data-testid="invite-user-button" className="inline-flex items-center gap-2 h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><Plus size={16} weight="bold" /> Add User</button></DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle className="font-display">Add Team Member</DialogTitle></DialogHeader>
            <form onSubmit={invite} className="space-y-3">
              <F label="Name" testid="invite-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <F label="Email" testid="invite-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
              <F label="Temporary password" testid="invite-password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
              <Sel label="Role" testid="invite-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} options={[{ value: "agent", label: "Agent" }, { value: "admin", label: "Admin" }]} />
              <DialogFooter><button data-testid="save-user-button" type="submit" className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Add</button></DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50"><th className="py-2.5 px-4 font-semibold">Name</th><th className="py-2.5 px-4 font-semibold">Email</th><th className="py-2.5 px-4 font-semibold">Role</th><th className="py-2.5 px-4 font-semibold text-right">Actions</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-border/60 hover:bg-muted/50">
                <td className="py-2.5 px-4 font-medium">{u.name}</td>
                <td className="py-2.5 px-4 text-muted-foreground">{u.email}</td>
                <td className="py-2.5 px-4"><span className={`text-xs px-2 py-0.5 rounded-sm font-semibold capitalize ${u.role === "admin" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>{u.role}</span></td>
                <td className="py-2.5 px-4 text-right space-x-2">
                  <button data-testid={`role-${u.id}`} onClick={() => changeRole(u)} className="text-xs text-primary hover:underline">{u.role === "admin" ? "Make agent" : "Make admin"}</button>
                  {u.id !== me?.id && <button data-testid={`delete-user-${u.id}`} onClick={() => remove(u.id)} className="text-muted-foreground hover:text-destructive"><Trash size={15} /></button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
