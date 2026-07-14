import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { StatusBadge, SentimentBadge } from "../components/StatusBadge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { MagnifyingGlass, Plus, Trash, PhoneCall, ShieldSlash, FileText, ChatText, Star } from "@phosphor-icons/react";
import { CallMonitor } from "../components/CallMonitor";

const STATUSES = ["all", "new", "contacted", "positive", "callback", "opted_out", "dnc"];

function RatingBadge({ value }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground text-xs">—</span>;
  const v = Number(value);
  const color = v >= 70 ? "text-success" : v >= 40 ? "text-warning-foreground" : "text-destructive";
  return <span className={`inline-flex items-center gap-1 text-xs font-semibold tnum ${color}`}><Star size={12} weight="fill" />{v}</span>;
}

function fmtDate(d) { return d ? new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—"; }

function CallbackCell({ at, type }) {
  if (!at) return <span className="text-xs text-muted-foreground">—</span>;
  const isAi = type === "ai";
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs whitespace-nowrap">{fmtDate(at)}</span>
      <span data-testid="callback-type-badge" className={`inline-flex w-fit items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide ${isAi ? "bg-primary/15 text-primary" : "bg-amber-100 text-amber-700"}`}>
        {isAi ? "AI" : "Human"}
      </span>
    </div>
  );
}

function hasTranscript(call) {
  return Array.isArray(call?.transcript) && call.transcript.length > 0;
}

export default function Leads() {
  const [contacts, setContacts] = useState([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [dialing, setDialing] = useState(null);
  const [viewer, setViewer] = useState(null); // { type: 'summary'|'transcript', call, name }
  const [callTarget, setCallTarget] = useState(null); // contact to dial
  const [campaigns, setCampaigns] = useState([]);
  const [callCampaignId, setCallCampaignId] = useState("");
  const [listenIn, setListenIn] = useState(true);
  const [monitorCallId, setMonitorCallId] = useState(null);
  const [form, setForm] = useState({ name: "", phone: "", email: "", company: "", notes: "", consent: false });
  const [cbDate, setCbDate] = useState("");
  const [cbType, setCbType] = useState("human");

  const load = useCallback(async () => {
    const params = {};
    if (filter !== "all") params.status = filter;
    if (search) params.search = search;
    const [{ data }, { data: camps }] = await Promise.all([api.get("/contacts", { params }), api.get("/campaigns")]);
    setContacts(data);
    setCampaigns(camps);
  }, [filter, search]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (detail) {
      setCbDate(detail.callback_at ? String(detail.callback_at).slice(0, 16) : "");
      setCbType(detail.callback_type || "human");
    }
  }, [detail?.id]);

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

  const saveCallback = async () => {
    if (!cbDate) { toast.error("Pick a callback date & time."); return; }
    await api.put(`/contacts/${detail.id}`, { status: "callback", callback_at: cbDate, callback_type: cbType });
    toast.success(`Callback scheduled (${cbType === "ai" ? "AI" : "Human"})`);
    load();
    openDetail(detail.id);
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

  const openCall = (contact, e) => {
    if (e) e.stopPropagation();
    setCallCampaignId("");
    setCallTarget(contact);
  };

  const confirmDial = async () => {
    const contact = callTarget;
    setDialing(contact.id);
    try {
      const { data } = await api.post("/calls/dial", { contact_id: contact.id, campaign_id: callCampaignId || null });
      const via = data.provider === "twilio" ? "Twilio" : "3CX";
      toast.success(`Calling ${contact.name} via ${via}${callCampaignId ? " · " + (campaigns.find((c) => c.id === callCampaignId)?.name || "campaign") : ""} (${data.status || "initiated"})`);
      const newCallId = data.call?.id;
      setCallTarget(null);
      if (listenIn && newCallId) setMonitorCallId(newCallId);
      load();
    } catch (err) { toast.error(apiErr(err)); }
    finally { setDialing(null); }
  };

  return (
    <div className="space-y-5 animate-fadeup" data-testid="leads-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display font-bold text-3xl tracking-tight">CRM · Leads</h1>
          <p className="text-sm text-muted-foreground mt-1">Multi-call history, ratings, summaries &amp; transcripts per lead.</p>
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

      <div className="bg-card border border-border rounded-sm overflow-x-auto">
        <table className="w-full text-sm min-w-[1080px]">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50">
              <th className="py-2.5 px-4 font-semibold">Name</th>
              <th className="py-2.5 px-4 font-semibold">Company</th>
              <th className="py-2.5 px-4 font-semibold">Phone</th>
              <th className="py-2.5 px-4 font-semibold">Email</th>
              <th className="py-2.5 px-4 font-semibold">Status</th>
              <th className="py-2.5 px-4 font-semibold">Rating</th>
              <th className="py-2.5 px-4 font-semibold">Last summary</th>
              <th className="py-2.5 px-4 font-semibold">Campaign</th>
              <th className="py-2.5 px-4 font-semibold">Last call</th>
              <th className="py-2.5 px-4 font-semibold">Callback</th>
              <th className="py-2.5 px-4 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => {
              const callable = !c.opted_out && !c.do_not_call && c.status !== "opted_out" && c.status !== "dnc";
              return (
              <tr key={c.id} data-testid={`lead-row-${c.id}`} onClick={() => openDetail(c.id)} className="border-b border-border/60 hover:bg-muted/50 cursor-pointer align-top">
                <td className="py-2.5 px-4 font-medium">
                  {c.name}
                  {c.call_count > 0 && <span className="ml-1.5 text-[10px] tnum text-muted-foreground">({c.call_count} call{c.call_count > 1 ? "s" : ""})</span>}
                </td>
                <td className="py-2.5 px-4 text-muted-foreground">{c.company || "—"}</td>
                <td className="py-2.5 px-4 tnum text-muted-foreground">{c.phone}</td>
                <td className="py-2.5 px-4 text-muted-foreground truncate max-w-[160px]">{c.email || "—"}</td>
                <td className="py-2.5 px-4"><StatusBadge status={c.status} /></td>
                <td className="py-2.5 px-4"><RatingBadge value={c.last_call_rating} /></td>
                <td className="py-2.5 px-4 text-muted-foreground max-w-[220px]">
                  {c.last_call_summary
                    ? <span className="line-clamp-2 text-xs">{c.last_call_summary}</span>
                    : <span className="text-xs">—</span>}
                </td>
                <td className="py-2.5 px-4 text-muted-foreground text-xs">{c.last_call_campaign || "—"}</td>
                <td className="py-2.5 px-4 text-muted-foreground text-xs whitespace-nowrap">{c.last_call_date ? fmtDate(c.last_call_date) : "—"}</td>
                <td className="py-2.5 px-4"><CallbackCell at={c.callback_at} type={c.callback_type} /></td>
                <td className="py-2.5 px-4 text-right">
                  <button data-testid={`call-lead-${c.id}`} disabled={!callable || dialing === c.id} onClick={(e) => openCall(c, e)}
                    title={callable ? "Call via 3CX / Twilio" : "Contact opted out / DNC"}
                    className="inline-flex items-center gap-1.5 h-8 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent hover:text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                    <PhoneCall size={14} weight="fill" /> {dialing === c.id ? "Calling…" : "Call"}
                  </button>
                </td>
              </tr>
            ); })}
            {contacts.length === 0 && <tr><td colSpan={10} className="py-10 text-center text-muted-foreground text-sm">No leads found.</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Lead detail sheet */}
      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
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

                <div data-testid="callback-scheduler">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2 font-semibold">Schedule callback</div>
                  {detail.callback_at && (
                    <div className="mb-2 text-xs text-muted-foreground">Current: <span className="text-foreground">{fmtDate(detail.callback_at)}</span>
                      <span className={`ml-2 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase ${detail.callback_type === "ai" ? "bg-primary/15 text-primary" : "bg-amber-100 text-amber-700"}`}>{detail.callback_type === "ai" ? "AI" : "Human"}</span>
                    </div>
                  )}
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input type="datetime-local" data-testid="callback-date-input" value={cbDate} onChange={(e) => setCbDate(e.target.value)}
                      className="h-9 flex-1 rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
                    <div className="inline-flex rounded-sm border border-border overflow-hidden">
                      {[["human", "Human"], ["ai", "AI"]].map(([v, label]) => (
                        <button key={v} type="button" data-testid={`callback-type-${v}`} onClick={() => setCbType(v)}
                          className={`h-9 px-3 text-xs font-semibold ${cbType === v ? "bg-primary text-primary-foreground" : "bg-card hover:bg-accent"}`}>{label}</button>
                      ))}
                    </div>
                    <button data-testid="save-callback-button" onClick={saveCallback} className="h-9 px-3 rounded-sm bg-primary text-primary-foreground text-xs font-semibold hover:opacity-90">Save callback</button>
                  </div>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2 font-semibold">Call history ({detail.calls?.length || 0})</div>
                  {detail.calls?.length ? detail.calls.map((c) => (
                    <div key={c.id} data-testid={`call-history-${c.id}`} className="border border-border rounded-sm p-3 mb-2 text-xs space-y-2">
                      <div className="flex justify-between items-start gap-2">
                        <div>
                          <div className="font-medium">{c.voice_name || (c.type === "manual" ? "Manual 3CX call" : "AI Call")}</div>
                          <div className="text-muted-foreground mt-0.5">{fmtDate(c.created_at)}</div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <RatingBadge value={c.rating} />
                          <SentimentBadge sentiment={c.sentiment} />
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
                        <span>Campaign: <span className="text-foreground">{c.campaign_name || "—"}</span></span>
                        <span>Status: <span className="text-foreground capitalize">{c.status || "—"}</span></span>
                      </div>
                      {c.summary && <div className="text-muted-foreground line-clamp-2">{c.summary}</div>}
                      <div className="flex gap-2 pt-1">
                        <button data-testid={`view-summary-${c.id}`} disabled={!c.summary} onClick={() => setViewer({ type: "summary", call: c, name: detail.name })}
                          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-sm border border-border text-[11px] font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed">
                          <FileText size={13} /> Summary
                        </button>
                        <button data-testid={`view-transcript-${c.id}`} disabled={!hasTranscript(c)} onClick={() => setViewer({ type: "transcript", call: c, name: detail.name })}
                          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-sm border border-border text-[11px] font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed">
                          <ChatText size={13} /> Transcript
                        </button>
                      </div>
                    </div>
                  )) : <div className="text-xs text-muted-foreground">No calls logged.</div>}
                </div>

                <div className="flex gap-2 pt-2 border-t border-border">
                  <button data-testid="call-lead-detail-button" onClick={() => openCall(detail)} disabled={detail.opted_out || detail.do_not_call || detail.status === "opted_out" || detail.status === "dnc" || dialing === detail.id}
                    className="flex-1 inline-flex items-center justify-center gap-1.5 h-9 rounded-sm bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-40">
                    <PhoneCall size={15} weight="fill" /> {dialing === detail.id ? "Calling…" : "Call"}
                  </button>
                  <button data-testid="dnc-lead-button" onClick={() => addDnc(detail.phone)} className="inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-sm border border-destructive/40 text-destructive text-sm font-medium hover:bg-destructive/10"><ShieldSlash size={15} weight="bold" /> DNC</button>
                  <button data-testid="delete-lead-button" onClick={() => remove(detail.id)} className="inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-sm border border-border text-muted-foreground text-sm hover:bg-accent"><Trash size={15} weight="bold" /></button>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* Campaign picker before dialing */}
      <Dialog open={!!callTarget} onOpenChange={(o) => !o && setCallTarget(null)}>
        <DialogContent data-testid="call-campaign-dialog">
          <DialogHeader><DialogTitle className="font-display">Call {callTarget?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Choose which campaign this call belongs to. The active telephony provider (3CX or Twilio) is used automatically based on your Settings.</p>
            <div>
              <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Campaign</label>
              <select data-testid="call-campaign-select" value={callCampaignId} onChange={(e) => setCallCampaignId(e.target.value)}
                className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="">Ad-hoc call (no campaign)</option>
                {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="text-xs text-muted-foreground tnum">Dialing: {callTarget?.phone}</div>
            <label data-testid="listen-in-toggle" className="flex items-center gap-2 text-sm cursor-pointer pt-1">
              <input type="checkbox" checked={listenIn} onChange={(e) => setListenIn(e.target.checked)} className="h-4 w-4" />
              Listen in on this call (live transcript + take over)
            </label>
          </div>
          <DialogFooter>
            <button data-testid="confirm-dial-button" onClick={confirmDial} disabled={dialing === callTarget?.id}
              className="inline-flex items-center gap-2 h-10 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90 disabled:opacity-60">
              <PhoneCall size={15} weight="fill" /> {dialing === callTarget?.id ? "Calling…" : "Call now"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CallMonitor callId={monitorCallId} onClose={() => setMonitorCallId(null)} />

      {/* Summary / Transcript viewer */}
      <Dialog open={!!viewer} onOpenChange={(o) => !o && setViewer(null)}>
        <DialogContent className="max-w-2xl" data-testid="call-viewer-dialog">
          {viewer && (
            <>
              <DialogHeader>
                <DialogTitle className="font-display flex items-center gap-2">
                  {viewer.type === "summary" ? <FileText size={18} /> : <ChatText size={18} />}
                  {viewer.type === "summary" ? "Call summary" : "Call transcript"} · {viewer.name}
                </DialogTitle>
              </DialogHeader>
              <div className="text-xs text-muted-foreground -mt-1 mb-1">
                {fmtDate(viewer.call.created_at)} · {viewer.call.campaign_name || "—"}
              </div>
              {viewer.type === "summary" ? (
                <div className="space-y-3 text-sm max-h-[60vh] overflow-y-auto">
                  <div className="flex items-center gap-3">
                    <RatingBadge value={viewer.call.rating} />
                    <SentimentBadge sentiment={viewer.call.sentiment} />
                  </div>
                  <p className="whitespace-pre-wrap leading-relaxed">{viewer.call.summary || "No summary available."}</p>
                  {viewer.call.next_action && (
                    <div className="border-t border-border pt-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground font-semibold mb-1">Next action</div>
                      <p className="text-sm">{viewer.call.next_action}</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
                  {hasTranscript(viewer.call) ? viewer.call.transcript.map((t, i) => (
                    <div key={i} className={`flex ${t.role === "agent" ? "justify-start" : "justify-end"}`}>
                      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${t.role === "agent" ? "bg-secondary" : "bg-primary text-primary-foreground"}`}>
                        <div className="text-[10px] uppercase tracking-wide opacity-70 mb-0.5">{t.role === "agent" ? "AI Agent" : "Prospect"}</div>
                        {t.content}
                      </div>
                    </div>
                  )) : <p className="text-sm text-muted-foreground">No transcript recorded for this call.</p>}
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
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
