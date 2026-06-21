import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import api, { apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Buildings, Brain, UserSwitch, FloppyDisk, Users, Megaphone, PhoneCall, AddressBook, Crown,
} from "@phosphor-icons/react";

export default function PlatformAdmin() {
  return (
    <div className="space-y-5 animate-fadeup" data-testid="platform-admin-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight flex items-center gap-2"><Crown size={26} weight="fill" className="text-primary" /> Platform Admin</h1>
        <p className="text-sm text-muted-foreground mt-1">Owner-only controls across all businesses on the platform.</p>
      </div>
      <Tabs defaultValue="businesses">
        <TabsList>
          <TabsTrigger value="businesses" data-testid="admin-tab-businesses"><Buildings size={16} className="mr-1.5" />Businesses</TabsTrigger>
          <TabsTrigger value="users" data-testid="admin-tab-users"><Users size={16} className="mr-1.5" />Users &amp; Impersonation</TabsTrigger>
          <TabsTrigger value="prompt" data-testid="admin-tab-prompt"><Brain size={16} className="mr-1.5" />Global AI Prompt</TabsTrigger>
        </TabsList>
        <TabsContent value="businesses" className="mt-4"><BusinessesTab /></TabsContent>
        <TabsContent value="users" className="mt-4"><UsersTab /></TabsContent>
        <TabsContent value="prompt" className="mt-4"><GlobalPromptTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function BusinessesTab() {
  const [orgs, setOrgs] = useState([]);
  useEffect(() => { api.get("/admin/businesses").then((r) => setOrgs(r.data)).catch((e) => toast.error(apiErr(e))); }, []);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {orgs.map((o) => (
        <div key={o.id} data-testid={`business-card-${o.id}`} className="bg-card border border-border rounded-sm p-4">
          <h3 className="font-display font-semibold text-lg">{o.name}</h3>
          <p className="text-xs text-muted-foreground tnum">Created {(o.created_at || "").slice(0, 10)}</p>
          <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
            <Stat icon={Users} label="Users" value={o.users} />
            <Stat icon={AddressBook} label="Contacts" value={o.contacts} />
            <Stat icon={Megaphone} label="Campaigns" value={o.campaigns} />
            <Stat icon={PhoneCall} label="Calls" value={o.calls} />
          </div>
        </div>
      ))}
      {orgs.length === 0 && <div className="col-span-full py-10 text-center text-sm text-muted-foreground border border-dashed border-border rounded-sm">No businesses yet.</div>}
    </div>
  );
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 bg-accent rounded-sm px-2.5 py-1.5">
      <Icon size={15} className="text-primary" weight="bold" />
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="ml-auto font-semibold tnum">{value}</span>
    </div>
  );
}

function UsersTab() {
  const { user, impersonate } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const load = useCallback(async () => { try { const r = await api.get("/admin/users"); setUsers(r.data); } catch (e) { toast.error(apiErr(e)); } }, []);
  useEffect(() => { load(); }, [load]);

  const doImpersonate = async (u) => {
    try { await impersonate(u.id); toast.success(`Now impersonating ${u.name}`); navigate("/dashboard"); }
    catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="bg-card border border-border rounded-sm overflow-hidden">
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50">
          <th className="py-2.5 px-4 font-semibold">Name</th><th className="py-2.5 px-4 font-semibold">Email</th><th className="py-2.5 px-4 font-semibold">Business</th><th className="py-2.5 px-4 font-semibold">Role</th><th className="py-2.5 px-4 font-semibold text-right">Actions</th>
        </tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} data-testid={`admin-user-row-${u.id}`} className="border-b border-border/60 hover:bg-muted/50">
              <td className="py-2.5 px-4 font-medium">{u.name}</td>
              <td className="py-2.5 px-4 text-muted-foreground">{u.email}</td>
              <td className="py-2.5 px-4 text-muted-foreground">{u.org_name}</td>
              <td className="py-2.5 px-4"><span className={`text-xs px-2 py-0.5 rounded-sm font-semibold capitalize ${u.role === "owner" ? "bg-primary/15 text-primary" : u.role === "admin" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>{u.role}</span></td>
              <td className="py-2.5 px-4 text-right">
                {u.id !== user?.id && u.role !== "owner" && (
                  <button data-testid={`impersonate-${u.id}`} onClick={() => doImpersonate(u)} className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline font-medium"><UserSwitch size={14} weight="bold" /> Impersonate</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GlobalPromptTab() {
  const [prompt, setPrompt] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { api.get("/admin/global-settings").then((r) => { setPrompt(r.data.ai_system_prompt || ""); setLoaded(true); }).catch((e) => toast.error(apiErr(e))); }, []);
  const save = async () => { try { await api.put("/admin/global-settings", { ai_system_prompt: prompt }); toast.success("Global AI prompt saved"); } catch (e) { toast.error(apiErr(e)); } };
  if (!loaded) return <div className="text-sm text-muted-foreground">Loading…</div>;
  return (
    <div className="bg-card border border-border rounded-sm p-5 space-y-3 max-w-3xl">
      <div className="flex items-center gap-2 font-display font-semibold"><Brain size={18} weight="bold" className="text-primary" /> Global AI system prompt</div>
      <p className="text-sm text-muted-foreground">This instruction is <b>prepended</b> to every AI interaction across all businesses (scripts, live calls, analysis). Each business can extend it with their own prompt in Settings → Organisation.</p>
      <textarea data-testid="global-prompt-input" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={10}
        placeholder="e.g. Always be polite, never make medical or financial guarantees, and respect UK cold-calling and GDPR rules."
        className="w-full rounded-sm border border-input bg-card p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      <button data-testid="save-global-prompt-button" onClick={save} className="inline-flex items-center gap-2 h-10 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><FloppyDisk size={16} weight="bold" /> Save Global Prompt</button>
    </div>
  );
}
