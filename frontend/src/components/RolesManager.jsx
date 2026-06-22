import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Plus, Trash, PencilSimple, ShieldStar } from "@phosphor-icons/react";

const ACTIONS = ["create", "read", "update", "delete"];

// platformScope: when true (owner), created roles apply to every business.
export default function RolesManager({ platformScope = false }) {
  const { hasCap, user } = useAuth();
  const canManage = hasCap("grant_privileges") || user?.role === "owner";
  const [systems, setSystems] = useState([]);
  const [caps, setCaps] = useState([]);
  const [roles, setRoles] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api.get("/systems"), api.get("/roles")]);
      setSystems(s.data.systems); setCaps(s.data.capabilities); setRoles(r.data);
    } catch (e) { toast.error(apiErr(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const blank = () => {
    const permissions = {}; systems.forEach((s) => { permissions[s] = { create: false, read: false, update: false, delete: false }; });
    return { id: null, name: "", permissions, capabilities: [] };
  };
  const startCreate = () => { setEditing(blank()); setOpen(true); };
  const startEdit = (r) => { setEditing({ id: r.id, name: r.name, permissions: JSON.parse(JSON.stringify(r.permissions)), capabilities: [...(r.capabilities || [])] }); setOpen(true); };

  const togglePerm = (sys, act) => setEditing((e) => ({ ...e, permissions: { ...e.permissions, [sys]: { ...e.permissions[sys], [act]: !e.permissions[sys][act] } } }));
  const toggleCap = (c) => setEditing((e) => ({ ...e, capabilities: e.capabilities.includes(c) ? e.capabilities.filter((x) => x !== c) : [...e.capabilities, c] }));

  const save = async () => {
    if (!editing.name.trim()) { toast.error("Role name is required"); return; }
    try {
      if (editing.id) {
        await api.put(`/roles/${editing.id}`, { name: editing.name, permissions: editing.permissions, capabilities: editing.capabilities });
      } else {
        const payload = { name: editing.name, permissions: editing.permissions, capabilities: editing.capabilities };
        if (platformScope) payload.scope = "platform";
        await api.post("/roles", payload);
      }
      toast.success("Role saved"); setOpen(false); setEditing(null); load();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const remove = async (r) => { try { await api.delete(`/roles/${r.id}`); toast.success("Role deleted"); load(); } catch (e) { toast.error(apiErr(e)); } };

  return (
    <div className="space-y-3" data-testid="roles-manager">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{platformScope ? "Default roles applied across every business." : "Roles for this business. Define exactly what each role can do."}</p>
        {canManage && <button data-testid="new-role-button" onClick={startCreate} className="inline-flex items-center gap-2 h-9 px-3 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><Plus size={15} weight="bold" /> New Role</button>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {roles.map((r) => (
          <div key={`${r.scope}-${r.name}`} data-testid={`role-card-${r.name}`} className="bg-card border border-border rounded-sm p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldStar size={17} weight="bold" className="text-primary" />
                <span className="font-display font-semibold capitalize">{r.name}</span>
              </div>
              <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 bg-accent rounded-sm font-semibold">{r.is_system ? "Built-in" : r.scope === "platform" ? "Platform" : "Business"}</span>
            </div>
            <div className="text-xs text-muted-foreground mt-2">
              {systems.filter((s) => r.permissions?.[s]?.read).length} systems readable · {(r.capabilities || []).length} privileges
            </div>
            {canManage && r.editable && (
              <div className="flex gap-2 mt-3">
                <button data-testid={`edit-role-${r.name}`} onClick={() => startEdit(r)} className="flex-1 inline-flex items-center justify-center gap-1.5 h-8 rounded-sm border border-border text-sm font-medium hover:bg-accent"><PencilSimple size={14} /> Edit</button>
                <button data-testid={`delete-role-${r.name}`} onClick={() => remove(r)} className="h-8 px-2.5 rounded-sm border border-border text-muted-foreground hover:text-destructive hover:bg-accent"><Trash size={15} /></button>
              </div>
            )}
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setEditing(null); }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader><DialogTitle className="font-display">{editing?.id ? "Edit role" : "New role"}</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-4 max-h-[70vh] overflow-y-auto">
              <div>
                <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Role name</label>
                <input data-testid="role-name-input" value={editing.name} disabled={!!editing.id} onChange={(e) => setEditing({ ...editing, name: e.target.value })} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm disabled:opacity-60" />
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground mb-1">CRUD access per system</div>
                <div className="border border-border rounded-sm overflow-hidden">
                  <table className="w-full text-xs">
                    <thead><tr className="bg-secondary/50 text-left"><th className="py-1.5 px-2">System</th>{ACTIONS.map((a) => <th key={a} className="py-1.5 px-2 capitalize text-center">{a}</th>)}</tr></thead>
                    <tbody>
                      {systems.map((s) => (
                        <tr key={s} className="border-t border-border/60">
                          <td className="py-1 px-2 font-medium">{s.replace(/_/g, " ")}</td>
                          {ACTIONS.map((a) => (
                            <td key={a} className="py-1 px-2 text-center">
                              <input type="checkbox" data-testid={`perm-${s}-${a}`} checked={!!editing.permissions[s]?.[a]} onChange={() => togglePerm(s, a)} className="h-4 w-4" />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground mb-1">Privileges</div>
                <div className="flex flex-wrap gap-2">
                  {caps.map((c) => (
                    <label key={c} className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm border text-xs cursor-pointer ${editing.capabilities.includes(c) ? "border-primary bg-primary/5 text-primary" : "border-border"}`}>
                      <input type="checkbox" data-testid={`cap-${c}`} checked={editing.capabilities.includes(c)} onChange={() => toggleCap(c)} className="h-3.5 w-3.5" />
                      {c.replace(/_/g, " ")}
                    </label>
                  ))}
                </div>
              </div>
            </div>
          )}
          <DialogFooter><button data-testid="save-role-button" onClick={save} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Save role</button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
