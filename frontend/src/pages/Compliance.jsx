import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  ShieldCheck, Clock, ProhibitInset, Trash, MagnifyingGlass, Plus, CheckCircle, XCircle, FileLock,
} from "@phosphor-icons/react";

export default function Compliance() {
  const [ov, setOv] = useState(null);
  const load = useCallback(async () => { const { data } = await api.get("/compliance/overview"); setOv(data); }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-5 animate-fadeup" data-testid="compliance-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Compliance Centre</h1>
        <p className="text-sm text-muted-foreground mt-1">UK cold-calling law (TPS/CTPS, calling hours) and GDPR — enforced.</p>
      </div>

      {ov && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <HoursCard hours={ov.calling_hours} />
          <Stat icon={ProhibitInset} label="On DNC List" value={ov.dnc_count} color="text-destructive" />
          <Stat icon={ShieldCheck} label="Opted Out" value={ov.opted_out} color="text-destructive" />
          <Stat icon={CheckCircle} label="Consented" value={`${ov.consented}/${ov.total_contacts}`} color="text-success" />
        </div>
      )}

      <Tabs defaultValue="dnc">
        <TabsList>
          <TabsTrigger value="dnc" data-testid="tab-dnc">Do-Not-Call</TabsTrigger>
          <TabsTrigger value="checker" data-testid="tab-checker">Number Checker</TabsTrigger>
          <TabsTrigger value="gdpr" data-testid="tab-gdpr">GDPR / Erasure</TabsTrigger>
        </TabsList>
        <TabsContent value="dnc" className="mt-4"><DncTab onChange={load} /></TabsContent>
        <TabsContent value="checker" className="mt-4"><CheckerTab /></TabsContent>
        <TabsContent value="gdpr" className="mt-4"><GdprTab onChange={load} /></TabsContent>
      </Tabs>
    </div>
  );
}

function HoursCard({ hours }) {
  return (
    <div className="bg-card border border-border rounded-sm p-4">
      <Clock size={18} weight="bold" className={hours.allowed ? "text-success" : "text-destructive"} />
      <div className="mt-2 text-sm font-bold">{hours.allowed ? "Calling allowed" : "Outside hours"}</div>
      <div className="text-xs text-muted-foreground mt-0.5 tnum">UK {hours.now} · {hours.start}–{hours.end}</div>
    </div>
  );
}
function Stat({ icon: Icon, label, value, color }) {
  return <div className="bg-card border border-border rounded-sm p-4"><Icon size={18} weight="bold" className={color} /><div className="mt-2 text-2xl font-bold tnum">{value}</div><div className="text-xs text-muted-foreground uppercase tracking-wide">{label}</div></div>;
}

function DncTab({ onChange }) {
  const [list, setList] = useState([]);
  const [phone, setPhone] = useState("");
  const load = useCallback(async () => { const { data } = await api.get("/compliance/dnc"); setList(data); }, []);
  useEffect(() => { load(); }, [load]);
  const add = async () => { if (!phone) return; try { await api.post("/compliance/dnc", { phone, reason: "manual" }); setPhone(""); load(); onChange(); toast.success("Added to DNC"); } catch (e) { toast.error(apiErr(e)); } };
  const remove = async (id) => { await api.delete(`/compliance/dnc/${id}`); load(); onChange(); };
  return (
    <div className="space-y-3">
      <div className="flex gap-2 max-w-md">
        <input data-testid="dnc-phone-input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+44 7700 900000" className="flex-1 h-10 px-3 rounded-sm border border-input bg-card text-sm tnum focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        <button data-testid="add-dnc-button" onClick={add} className="inline-flex items-center gap-1.5 h-10 px-4 bg-foreground text-background rounded-sm text-sm font-medium"><Plus size={15} weight="bold" /> Add</button>
      </div>
      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50"><th className="py-2.5 px-4 font-semibold">Phone</th><th className="py-2.5 px-4 font-semibold">Reason</th><th className="py-2.5 px-4 font-semibold text-right">Action</th></tr></thead>
          <tbody>
            {list.map((d) => (
              <tr key={d.id} className="border-b border-border/60 hover:bg-muted/50">
                <td className="py-2.5 px-4 tnum font-medium">{d.phone}</td>
                <td className="py-2.5 px-4 text-muted-foreground text-xs capitalize">{(d.reason || "").replace(/_/g, " ")}</td>
                <td className="py-2.5 px-4 text-right"><button data-testid={`remove-dnc-${d.id}`} onClick={() => remove(d.id)} className="text-muted-foreground hover:text-destructive"><Trash size={15} /></button></td>
              </tr>
            ))}
            {list.length === 0 && <tr><td colSpan={3} className="py-8 text-center text-muted-foreground text-sm">DNC list is empty.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CheckerTab() {
  const [phone, setPhone] = useState("");
  const [res, setRes] = useState(null);
  const check = async () => { if (!phone) return; const { data } = await api.get("/compliance/check", { params: { phone } }); setRes(data); };
  return (
    <div className="max-w-md space-y-3">
      <p className="text-sm text-muted-foreground">Verify a number is safe to call (not on DNC, within UK calling hours).</p>
      <div className="flex gap-2">
        <div className="relative flex-1"><MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><input data-testid="check-phone-input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+44 7700 900000" className="h-10 w-full pl-9 pr-3 rounded-sm border border-input bg-card text-sm tnum focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>
        <button data-testid="check-number-button" onClick={check} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Check</button>
      </div>
      {res && (
        <div data-testid="check-result" className={`border rounded-sm p-4 ${res.callable ? "border-success/40 bg-success/10" : "border-destructive/40 bg-destructive/10"}`}>
          <div className="flex items-center gap-2 font-semibold">{res.callable ? <CheckCircle size={20} weight="fill" className="text-success" /> : <XCircle size={20} weight="fill" className="text-destructive" />}{res.callable ? "Safe to call" : "Do NOT call"}</div>
          <ul className="mt-2 text-sm space-y-1">
            <li className="flex justify-between"><span className="text-muted-foreground">On DNC list</span><span className={res.on_dnc ? "text-destructive font-semibold" : ""}>{res.on_dnc ? "Yes" : "No"}</span></li>
            <li className="flex justify-between"><span className="text-muted-foreground">Within calling hours</span><span className={!res.calling_hours.allowed ? "text-destructive font-semibold" : ""}>{res.calling_hours.allowed ? "Yes" : "No"}</span></li>
          </ul>
        </div>
      )}
    </div>
  );
}

function GdprTab({ onChange }) {
  const [contacts, setContacts] = useState([]);
  const [erasures, setErasures] = useState([]);
  const load = useCallback(async () => {
    const [c, e] = await Promise.all([api.get("/contacts"), api.get("/compliance/erasure")]);
    setContacts(c.data); setErasures(e.data);
  }, []);
  useEffect(() => { load(); }, [load]);
  const erase = async (id) => {
    if (!window.confirm("Permanently erase this contact and all call records? This cannot be undone (GDPR Art. 17).")) return;
    try { await api.post("/compliance/erasure", { contact_id: id }); toast.success("Erased"); load(); onChange(); } catch (e) { toast.error(apiErr(e)); }
  };
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="bg-card border border-border rounded-sm p-4">
        <div className="flex items-center gap-1.5 text-sm font-semibold mb-3"><FileLock size={16} weight="bold" /> Right to Erasure</div>
        <p className="text-xs text-muted-foreground mb-3">Action a data subject's request to be forgotten. Removes the contact and all associated call data.</p>
        <div className="max-h-80 overflow-y-auto space-y-1.5">
          {contacts.map((c) => (
            <div key={c.id} className="flex items-center justify-between border border-border rounded-sm px-3 py-2">
              <div><div className="text-sm font-medium">{c.name}</div><div className="text-xs text-muted-foreground tnum">{c.phone}</div></div>
              <button data-testid={`erase-${c.id}`} onClick={() => erase(c.id)} className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-sm border border-destructive/40 text-destructive text-xs font-medium hover:bg-destructive/10"><Trash size={13} weight="bold" /> Erase</button>
            </div>
          ))}
        </div>
      </div>
      <div className="bg-card border border-border rounded-sm p-4">
        <div className="text-sm font-semibold mb-3">Erasure Audit Log</div>
        {erasures.length ? erasures.map((e) => (
          <div key={e.id} className="border-b border-border/60 py-2 text-sm">
            <div className="flex justify-between"><span className="font-medium">{e.contact_name}</span><span className="text-xs text-muted-foreground tnum">{(e.created_at || "").slice(0, 10)}</span></div>
            <div className="text-xs text-muted-foreground">Requested by {e.requested_by}</div>
          </div>
        )) : <div className="text-sm text-muted-foreground">No erasure requests yet.</div>}
      </div>
    </div>
  );
}
