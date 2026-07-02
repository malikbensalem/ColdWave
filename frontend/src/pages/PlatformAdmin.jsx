import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import api, { apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import RolesManager from "../components/RolesManager";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import {
  Buildings, Brain, UserSwitch, FloppyDisk, Users, Megaphone, PhoneCall, AddressBook, Crown,
  Plus, Trash, Star, MagnifyingGlass, ShieldStar,
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
          <TabsTrigger value="blueprints" data-testid="admin-tab-blueprints"><Brain size={16} className="mr-1.5" />AI Blueprints</TabsTrigger>
          <TabsTrigger value="roles" data-testid="admin-tab-roles"><ShieldStar size={16} className="mr-1.5" />Default Roles</TabsTrigger>
        </TabsList>
        <TabsContent value="businesses" className="mt-4"><BusinessesTab /></TabsContent>
        <TabsContent value="users" className="mt-4"><UsersTab /></TabsContent>
        <TabsContent value="blueprints" className="mt-4"><BlueprintsTab /></TabsContent>
        <TabsContent value="roles" className="mt-4"><RolesManager platformScope /></TabsContent>
      </Tabs>
    </div>
  );
}

function BusinessesTab() {
  const [orgs, setOrgs] = useState([]);
  const [blueprints, setBlueprints] = useState([]);
  const [search, setSearch] = useState("");
  const load = useCallback(async () => {
    try {
      const [o, b] = await Promise.all([api.get(`/admin/businesses${search ? `?search=${encodeURIComponent(search)}` : ""}`), api.get("/admin/blueprints")]);
      setOrgs(o.data); setBlueprints(b.data);
    } catch (e) { toast.error(apiErr(e)); }
  }, [search]);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [load]);

  const assignChannel = async (oid, channel, bid) => {
    try { await api.put(`/admin/businesses/${oid}/channel-blueprint`, { channel, blueprint_id: bid || null }); toast.success(`${channel} blueprint set`); load(); }
    catch (e) { toast.error(apiErr(e)); }
  };
  const toggleBan = async (o) => {
    try {
      if (o.banned) { await api.post(`/admin/businesses/${o.id}/unban`); toast.success("Business reinstated"); }
      else { const reason = window.prompt(`Suspend "${o.name}"? This blocks all its users. Reason:`, "Policy violation"); if (reason === null) return; await api.post(`/admin/businesses/${o.id}/ban`, { reason }); toast.success("Business suspended"); }
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="space-y-3">
      <SearchBox value={search} onChange={setSearch} placeholder="Search businesses…" testid="business-search" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {orgs.map((o) => (
          <div key={o.id} data-testid={`business-card-${o.id}`} className={`bg-card border rounded-sm p-4 ${o.banned ? "border-destructive/50" : "border-border"}`}>
            <div className="flex items-center justify-between">
              <h3 className="font-display font-semibold text-lg">{o.name}</h3>
              {o.banned && <span data-testid={`business-banned-${o.id}`} className="text-[10px] uppercase px-1.5 py-0.5 bg-destructive/15 text-destructive rounded-sm">Suspended</span>}
            </div>
            <p className="text-xs text-muted-foreground tnum">Created {(o.created_at || "").slice(0, 10)}</p>
            <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
              <Stat icon={Users} label="Users" value={o.users} />
              <Stat icon={AddressBook} label="Contacts" value={o.contacts} />
              <Stat icon={Megaphone} label="Campaigns" value={o.campaigns} />
              <Stat icon={PhoneCall} label="Calls" value={o.calls} />
            </div>
            <div className="mt-3 space-y-2">
              {[["call", "Call"], ["whatsapp", "WhatsApp"], ["sms", "SMS"]].map(([ch, label]) => (
                <div key={ch}>
                  <label className="text-[10px] uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label} blueprint</label>
                  <select data-testid={`assign-${ch}-blueprint-${o.id}`} value={(o.channel_blueprints || {})[ch] || ""} onChange={(e) => assignChannel(o.id, ch, e.target.value)} className="mt-1 flex h-8 w-full rounded-sm border border-input bg-card px-2 text-xs">
                    <option value="">— default —</option>
                    {blueprints.filter((b) => !b.channel || b.channel === "global" || b.channel === ch).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <button data-testid={`toggle-ban-business-${o.id}`} onClick={() => toggleBan(o)} className={`mt-3 w-full h-8 rounded-sm text-sm font-medium border ${o.banned ? "border-success/40 text-success hover:bg-success/10" : "border-destructive/40 text-destructive hover:bg-destructive/10"}`}>{o.banned ? "Reinstate business" : "Suspend business"}</button>
          </div>
        ))}
        {orgs.length === 0 && <div className="col-span-full py-10 text-center text-sm text-muted-foreground border border-dashed border-border rounded-sm">No businesses match.</div>}
      </div>
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

function SearchBox({ value, onChange, placeholder, testid }) {
  return (
    <div className="relative max-w-sm">
      <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <input data-testid={testid} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="h-10 w-full pl-9 pr-3 rounded-sm border border-input bg-card text-sm" />
    </div>
  );
}

function UsersTab() {
  const { user, impersonate } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [filters, setFilters] = useState({ search: "", role: "", org_id: "" });
  const [roleDlg, setRoleDlg] = useState(false);
  const [rolePreview, setRolePreview] = useState({ org_id: "", role: "agent" });

  const load = useCallback(async () => {
    try {
      const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v));
      const [u, b] = await Promise.all([api.get("/admin/users", { params }), api.get("/admin/businesses")]);
      setUsers(u.data); setOrgs(b.data);
    } catch (e) { toast.error(apiErr(e)); }
  }, [filters]);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [load]);

  const doImpersonateUser = async (u) => {
    try { await impersonate(u.id); toast.success(`Now impersonating ${u.name}`); navigate("/dashboard"); }
    catch (e) { toast.error(apiErr(e)); }
  };
  const doImpersonateRole = async () => {
    try {
      await impersonate(null, rolePreview);
      toast.success(`Previewing the ${rolePreview.role} role`); navigate("/dashboard");
    } catch (e) { toast.error(apiErr(e)); }
  };
  const roleOptions = [...new Set(users.map((u) => u.role))].filter((r) => r !== "owner");

  const toggleBan = async (u) => {
    try {
      if (u.banned) { await api.post(`/admin/users/${u.id}/unban`); toast.success(`${u.name} reinstated`); }
      else { const reason = window.prompt(`Ban ${u.name}? Reason:`, "Policy violation"); if (reason === null) return; await api.post(`/admin/users/${u.id}/ban`, { reason }); toast.success(`${u.name} banned`); }
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const changeRole = async (u, role) => {
    if (!role || role === u.role) return;
    try { await api.put(`/admin/users/${u.id}/role`, { role }); toast.success(`${u.name} is now ${role}`); load(); }
    catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-2 flex-wrap">
        <SearchBox value={filters.search} onChange={(v) => setFilters({ ...filters, search: v })} placeholder="Search name or email…" testid="user-search" />
        <select data-testid="user-filter-role" value={filters.role} onChange={(e) => setFilters({ ...filters, role: e.target.value })} className="h-10 px-3 rounded-sm border border-input bg-card text-sm capitalize">
          <option value="">All roles</option>
          {[...new Set(["owner", "admin", "agent", ...roleOptions])].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select data-testid="user-filter-business" value={filters.org_id} onChange={(e) => setFilters({ ...filters, org_id: e.target.value })} className="h-10 px-3 rounded-sm border border-input bg-card text-sm">
          <option value="">All businesses</option>
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <Dialog open={roleDlg} onOpenChange={setRoleDlg}>
          <DialogTrigger asChild><button data-testid="impersonate-role-button" className="ml-auto inline-flex items-center gap-1.5 h-10 px-4 border border-border rounded-sm text-sm font-medium hover:bg-accent"><UserSwitch size={15} weight="bold" /> Preview a role</button></DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle className="font-display">Preview as a role</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div>
                <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Business</label>
                <select data-testid="preview-role-business" value={rolePreview.org_id} onChange={(e) => setRolePreview({ ...rolePreview, org_id: e.target.value })} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm">
                  <option value="">— select business —</option>
                  {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Role</label>
                <input data-testid="preview-role-name" value={rolePreview.role} onChange={(e) => setRolePreview({ ...rolePreview, role: e.target.value })} placeholder="agent, admin, or a custom role name" className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm" />
              </div>
            </div>
            <DialogFooter><button data-testid="start-role-preview" onClick={doImpersonateRole} disabled={!rolePreview.org_id || !rolePreview.role} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium disabled:opacity-50">Start preview</button></DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50">
            <th className="py-2.5 px-4 font-semibold">Name</th><th className="py-2.5 px-4 font-semibold">Email</th><th className="py-2.5 px-4 font-semibold">Business</th><th className="py-2.5 px-4 font-semibold">Role</th><th className="py-2.5 px-4 font-semibold text-right">Actions</th>
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`admin-user-row-${u.id}`} className="border-b border-border/60 hover:bg-muted/50">
                <td className="py-2.5 px-4 font-medium">{u.name}{u.banned && <span className="ml-2 text-[10px] uppercase px-1.5 py-0.5 bg-destructive/15 text-destructive rounded-sm">Banned</span>}</td>
                <td className="py-2.5 px-4 text-muted-foreground">{u.email}</td>
                <td className="py-2.5 px-4 text-muted-foreground">{u.org_name}</td>
                <td className="py-2.5 px-4"><span className={`text-xs px-2 py-0.5 rounded-sm font-semibold capitalize ${u.role === "owner" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>{u.role}</span></td>
                <td className="py-2.5 px-4 text-right">
                  {u.role !== "owner" && (
                    <div className="inline-flex items-center gap-2 justify-end">
                      <select data-testid={`change-role-${u.id}`} value={u.role} onChange={(e) => changeRole(u, e.target.value)} className="h-7 rounded-sm border border-input bg-card px-1.5 text-xs capitalize">
                        {[...new Set(["admin", "agent", ...roleOptions, u.role])].map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                      <button data-testid={`toggle-ban-${u.id}`} onClick={() => toggleBan(u)} className={`text-xs font-medium hover:underline ${u.banned ? "text-success" : "text-destructive"}`}>{u.banned ? "Unban" : "Ban"}</button>
                      {u.id !== user?.id && !u.banned && (
                        <button data-testid={`impersonate-${u.id}`} onClick={() => doImpersonateUser(u)} className="inline-flex items-center gap-1 text-xs text-primary hover:underline font-medium"><UserSwitch size={13} weight="bold" /> Impersonate</button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BlueprintsTab() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ id: null, name: "", prompt: "", is_default: false, channel: "global" });
  const load = useCallback(async () => { try { const r = await api.get("/admin/blueprints"); setItems(r.data); } catch (e) { toast.error(apiErr(e)); } }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form.name.trim()) { toast.error("Name required"); return; }
    try {
      if (form.id) await api.put(`/admin/blueprints/${form.id}`, { name: form.name, prompt: form.prompt, channel: form.channel, is_default: form.is_default || undefined });
      else await api.post("/admin/blueprints", { name: form.name, prompt: form.prompt, channel: form.channel, is_default: form.is_default });
      toast.success("Blueprint saved"); setOpen(false); setForm({ id: null, name: "", prompt: "", is_default: false, channel: "global" }); load();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const setDefault = async (b) => { try { await api.put(`/admin/blueprints/${b.id}`, { is_default: true }); toast.success(`${b.name} is now the default`); load(); } catch (e) { toast.error(apiErr(e)); } };
  const remove = async (b) => { try { await api.delete(`/admin/blueprints/${b.id}`); toast.success("Deleted"); load(); } catch (e) { toast.error(apiErr(e)); } };

  const CH = { global: "All channels", call: "Call", whatsapp: "WhatsApp", sms: "SMS", email: "Email" };
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Reusable AI system prompts. Tag each for a channel (call / WhatsApp / SMS) and assign them per business below.</p>
        <button data-testid="new-blueprint-button" onClick={() => { setForm({ id: null, name: "", prompt: "", is_default: false, channel: "global" }); setOpen(true); }} className="inline-flex items-center gap-2 h-9 px-3 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><Plus size={15} weight="bold" /> New Blueprint</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {items.map((b) => (
          <div key={b.id} data-testid={`blueprint-card-${b.id}`} className="bg-card border border-border rounded-sm p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><Brain size={17} weight="bold" className="text-primary" /><span className="font-display font-semibold">{b.name}</span>{b.is_default && <span className="text-[10px] uppercase px-1.5 py-0.5 bg-primary/15 text-primary rounded-sm inline-flex items-center gap-1"><Star size={10} weight="fill" />Default</span>}</div>
              <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 bg-accent rounded-sm font-semibold" data-testid={`blueprint-channel-${b.id}`}>{CH[b.channel] || "All channels"}</span>
            </div>
            <p className="text-xs text-muted-foreground mt-2 line-clamp-3">{b.prompt}</p>
            <div className="flex gap-2 mt-3">
              <button data-testid={`edit-blueprint-${b.id}`} onClick={() => { setForm({ id: b.id, name: b.name, prompt: b.prompt, is_default: b.is_default, channel: b.channel || "global" }); setOpen(true); }} className="flex-1 h-8 rounded-sm border border-border text-sm font-medium hover:bg-accent">Edit</button>
              {!b.is_default && <button data-testid={`default-blueprint-${b.id}`} onClick={() => setDefault(b)} className="h-8 px-2.5 rounded-sm border border-border text-sm hover:bg-accent">Set default</button>}
              {!b.is_default && <button data-testid={`delete-blueprint-${b.id}`} onClick={() => remove(b)} className="h-8 px-2.5 rounded-sm border border-border text-muted-foreground hover:text-destructive hover:bg-accent"><Trash size={15} /></button>}
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle className="font-display">{form.id ? "Edit blueprint" : "New blueprint"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Name</label>
              <input data-testid="blueprint-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm" /></div>
            <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Channel</label>
              <select data-testid="blueprint-channel-select" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm">
                {Object.entries(CH).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select></div>
            <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Prompt</label>
              <textarea data-testid="blueprint-prompt" value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} rows={8} className="mt-1 w-full rounded-sm border border-input bg-card p-3 text-sm" /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" data-testid="blueprint-default" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} className="h-4 w-4" /> Set as default for new businesses</label>
          </div>
          <DialogFooter><button data-testid="save-blueprint-button" onClick={save} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium"><FloppyDisk size={15} className="inline mr-1.5" />Save</button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
