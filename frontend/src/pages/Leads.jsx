import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { StatusBadge, SentimentBadge } from "../components/StatusBadge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { MagnifyingGlass, Plus, Trash, PhoneCall, ShieldSlash } from "@phosphor-icons/react";

const STATUSES = ["all", "new", "contacted", "positive", "callback", "opted_out", "dnc"];

export default function Leads() {
  const [contacts, setContacts] = useState([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState({ name: "", phone: "", email: "", company: "", notes: "", consent: false });

  const load = useCallback(async () => {
    const params = {};
    if (filter !== "all") params.status = filter;
    if (search) params.search = search;
    const { data } = await api.get("/contacts", { params });
    setContacts(data);
  }, [filter, search]);

  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e.preventDefault();
    try {
      await api.post("/contacts", form);
      toast.success("Lead added");
      setOpen(false);
      setForm({ name: "", phone: "", email: "", company: "", notes: "", consent: false });
      load();
    } catch (err) { toast.error(apiErr(err)); }
  };

  const openDetail = async (id) => {
    const { data } = await api.get(`/contacts/${id}`);
    setDetail(data);
  };

  const setStatus = async (id, status) => {
    await api.put(`/contacts/${id}`, { status });
    toast.success("Status updated");
    load();
    if (detail?.id === id) openDetail(id);
  };

  const addDnc = async (phone) => {
    await api.post("/compliance/dnc", { phone, reason: "manual" });
    toast.success("Added to Do-Not-Call list");
    load();
    setDetail(null);
  };

  const remove = async (id) => {
    await api.delete(`/contacts/${id}`);
    toast.success("Lead removed");
    load();
    setDetail(null);
  };

  return (
    <div className="space-y-5 animate-fadeup" data-testid="leads-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display font-bold text-3xl tracking-tight">CRM · Leads</h1>
          <p className="text-sm text-muted-foreground mt-1">Track who you're calling and who responded positively.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <button data-testid="add-lead-button" className="inline-flex items-center gap-2 h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90 active:scale-[0.99] transition-all">
              <Plus size={16} weight="bold" /> Add Lead
            </button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle className="font-display">New Lead</DialogTitle></DialogHeader>
            <form onSubmit={create} className="space-y-3">
              <Inp label="Name" testid="lead-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <Inp label="Phone" testid="lead-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} required />
              <Inp label="Email" testid="lead-email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <Inp label="Company" testid="lead-company" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" data-testid="lead-consent" checked={form.consent} onChange={(e) => setForm({ ...form, consent: e.target.checked })} />
                Prior marketing consent on record (GDPR)
              </label>
              <DialogFooter>
                <button data-testid="save-lead-button" type="submit" className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Save Lead</button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input data-testid="lead-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, phone, company…"
            className="h-10 w-full pl-9 pr-3 rounded-sm border border-input bg-card text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <div className="flex gap-1 flex-wrap">
          {STATUSES.map((s) => (
            <button key={s} data-testid={`filter-${s}`} onClick={() => setFilter(s)}
              className={`px-3 h-10 rounded-sm text-xs font-semibold capitalize border transition-colors ${filter === s ? "bg-primary text-primary-foreground border-primary" : "bg-card border-border text-muted-foreground hover:bg-accent"}`}>
              {s === "opted_out" ? "Opted out" : s}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-card border border-border rounded-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50">
              <th className="py-2.5 px-4 font-semibold">Name</th>
              <th className="py-2.5 px-4 font-semibold">Company</th>
              <th className="py-2.5 px-4 font-semibold">Phone</th>
              <th className="py-2.5 px-4 font-semibold">Status</th>
              <th className="py-2.5 px-4 font-semibold">Sentiment</th>
              <th className="py-2.5 px-4 font-semibold">Consent</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => (
              <tr key={c.id} data-testid={`lead-row-${c.id}`} onClick={() => openDetail(c.id)} className="border-b border-border/60 hover:bg-muted/50 cursor-pointer">
                <td className="py-2.5 px-4 font-medium">{c.name}</td>
                <td className="py-2.5 px-4 text-muted-foreground">{c.company || "—"}</td>
                <td className="py-2.5 px-4 tnum text-muted-foreground">{c.phone}</td>
                <td className="py-2.5 px-4"><StatusBadge status={c.status} /></td>
                <td className="py-2.5 px-4"><SentimentBadge sentiment={c.sentiment} /></td>
                <td className="py-2.5 px-4">{c.consent ? <span className="text-success text-xs font-semibold">Yes</span> : <span className="text-muted-foreground text-xs">No</span>}</td>
              </tr>
            ))}
            {contacts.length === 0 && <tr><td colSpan={6} className="py-10 text-center text-muted-foreground text-sm">No leads found.</td></tr>}
          </tbody>
        </table>
      </div>

      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent className="w-full sm:max-w-md overflow-y-auto">
          {detail && (
            <>
              <SheetHeader><SheetTitle className="font-display text-2xl">{detail.name}</SheetTitle></SheetHeader>
              <div className="mt-4 space-y-4">
                <div className="flex items-center gap-2"><StatusBadge status={detail.status} /><SentimentBadge sentiment={detail.sentiment} /></div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <Info label="Company" value={detail.company} />
                  <Info label="Phone" value={detail.phone} mono />
                  <Info label="Email" value={detail.email} />
                  <Info label="Consent" value={detail.consent ? "Yes" : "No"} />
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2 font-semibold">Set status</div>
                  <div className="flex gap-1 flex-wrap">
                    {["new", "contacted", "positive", "callback"].map((s) => (
                      <button key={s} data-testid={`set-status-${s}`} onClick={() => setStatus(detail.id, s)} className="px-3 h-8 rounded-sm text-xs font-semibold capitalize border border-border hover:bg-accent">{s}</button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2 font-semibold">Call history</div>
                  {detail.calls?.length ? detail.calls.map((c) => (
                    <div key={c.id} className="border border-border rounded-sm p-2.5 mb-2 text-xs">
                      <div className="flex justify-between"><span className="font-medium">{c.voice_name || "AI Call"}</span><SentimentBadge sentiment={c.sentiment} /></div>
                      <div className="text-muted-foreground mt-1">{c.analysis?.summary || c.status}</div>
                    </div>
                  )) : <div className="text-xs text-muted-foreground">No calls logged.</div>}
                </div>

                <div className="flex gap-2 pt-2 border-t border-border">
                  <button data-testid="dnc-lead-button" onClick={() => addDnc(detail.phone)} className="flex-1 inline-flex items-center justify-center gap-1.5 h-9 rounded-sm border border-destructive/40 text-destructive text-sm font-medium hover:bg-destructive/10"><ShieldSlash size={15} weight="bold" /> Add to DNC</button>
                  <button data-testid="delete-lead-button" onClick={() => remove(detail.id)} className="inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-sm border border-border text-muted-foreground text-sm hover:bg-accent"><Trash size={15} weight="bold" /></button>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Inp({ label, testid, ...rest }) {
  return (
    <div>
      <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label>
      <input data-testid={testid} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
    </div>
  );
}
function Info({ label, value, mono }) {
  return <div><div className="text-xs text-muted-foreground">{label}</div><div className={`font-medium ${mono ? "tnum" : ""}`}>{value || "—"}</div></div>;
}
