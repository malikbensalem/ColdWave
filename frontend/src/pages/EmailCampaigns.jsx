import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import {
  EnvelopeSimple, Plus, Trash, PaperPlaneTilt, GoogleLogo, MicrosoftOutlookLogo, Clock, ArrowsClockwise, CheckCircle, Plugs, Users,
} from "@phosphor-icons/react";

const AUDIENCES = [
  { value: "all", label: "All contacts (with email)" },
  { value: "positive", label: "Positive responders" },
  { value: "contacted", label: "Contacted" },
  { value: "consented", label: "Consented only" },
];

export default function EmailCampaigns() {
  const { can } = useAuth();
  const isAdmin = can("email_campaigns", "create");
  const [integration, setIntegration] = useState(null);
  const [campaigns, setCampaigns] = useState([]);

  const load = useCallback(async () => {
    try {
      const [i, c] = await Promise.all([api.get("/email/integration"), api.get("/email-campaigns")]);
      setIntegration(i.data); setCampaigns(c.data);
    } catch (e) { toast.error(apiErr(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-5 animate-fadeup" data-testid="email-campaigns-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Email Campaigns</h1>
        <p className="text-sm text-muted-foreground mt-1">Connect Office 365 or Gmail and schedule outreach. <span className="text-warning-foreground">Sending runs in mock mode.</span></p>
      </div>

      <ConnectionCard integration={integration} isAdmin={isAdmin} reload={load} />

      <div className="flex items-center justify-between">
        <h2 className="font-display font-semibold text-lg">Campaigns</h2>
        <NewCampaignDialog connected={integration?.connected} reload={load} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {campaigns.map((c) => <CampaignCard key={c.id} c={c} reload={load} />)}
        {campaigns.length === 0 && <div className="col-span-full py-10 text-center text-sm text-muted-foreground border border-dashed border-border rounded-sm">No email campaigns yet — create one above.</div>}
      </div>
    </div>
  );
}

function ConnectionCard({ integration, isAdmin, reload }) {
  const [provider, setProvider] = useState("gmail");
  const [email, setEmail] = useState("");

  const connect = async () => {
    if (!email.trim()) { toast.error("Enter the mailbox email address to connect."); return; }
    try { await api.put("/email/integration", { provider, account_email: email }); toast.success("Mailbox connected (mock)"); reload(); }
    catch (e) { toast.error(apiErr(e)); }
  };
  const disconnect = async () => { try { await api.delete("/email/integration"); toast.success("Disconnected"); reload(); } catch (e) { toast.error(apiErr(e)); } };

  return (
    <div className="bg-card border border-border rounded-sm p-5 space-y-3" data-testid="email-connection-card">
      <div className="flex items-center gap-2 font-display font-semibold"><Plugs size={18} weight="bold" className="text-primary" /> Email provider connection</div>
      {integration?.connected ? (
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2 text-sm" data-testid="email-connected-status">
            {integration.provider === "gmail" ? <GoogleLogo size={18} weight="bold" className="text-destructive" /> : <MicrosoftOutlookLogo size={18} weight="bold" className="text-primary" />}
            <CheckCircle size={16} weight="fill" className="text-success" />
            Connected: <b className="capitalize">{integration.provider === "o365" ? "Office 365" : "Gmail"}</b> · {integration.account_email}
          </div>
          {isAdmin && <button data-testid="email-disconnect-button" onClick={disconnect} className="h-9 px-3 rounded-sm border border-border text-xs font-medium hover:bg-accent">Disconnect</button>}
        </div>
      ) : isAdmin ? (
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Provider</label>
            <select data-testid="email-provider-select" value={provider} onChange={(e) => setProvider(e.target.value)} className="mt-1 flex h-10 w-48 rounded-sm border border-input bg-card px-3 text-sm">
              <option value="gmail">Gmail</option>
              <option value="o365">Office 365</option>
            </select>
          </div>
          <div className="flex-1 min-w-[220px]">
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Mailbox email</label>
            <input data-testid="email-account-input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="sales@yourcompany.co.uk" className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm" />
          </div>
          <button data-testid="email-connect-button" onClick={connect} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90">Connect</button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No mailbox connected. Ask an admin to connect Office 365 or Gmail.</p>
      )}
      <p className="text-xs text-muted-foreground">OAuth connection is mocked for now — emails are not actually delivered. Recipients are pulled from your CRM contacts (excluding opted-out).</p>
    </div>
  );
}

function NewCampaignDialog({ connected, reload }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", subject: "", body: "", audience: "all", schedule_type: "now", scheduled_at: "", recurrence: "daily" });
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    if (!open) return;
    api.get(`/email/recipients?audience=${form.audience}`).then((r) => setPreview(r.data)).catch(() => setPreview(null));
  }, [open, form.audience]);

  const submit = async (e) => {
    e.preventDefault();
    const payload = { name: form.name, subject: form.subject, body: form.body, audience: form.audience, schedule_type: form.schedule_type };
    if (form.schedule_type !== "now") {
      if (!form.scheduled_at) { toast.error("Pick a date & time"); return; }
      payload.scheduled_at = new Date(form.scheduled_at).toISOString();
      if (form.schedule_type === "recurring") payload.recurrence = form.recurrence;
    }
    try {
      const { data } = await api.post("/email-campaigns", payload);
      toast.success(form.schedule_type === "now" ? `Sent (mock) to ${data.sent_count} recipients` : "Campaign scheduled");
      setOpen(false);
      setForm({ name: "", subject: "", body: "", audience: "all", schedule_type: "now", scheduled_at: "", recurrence: "daily" });
      reload();
    } catch (err) { toast.error(apiErr(err)); }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button data-testid="new-email-campaign-button" disabled={!connected} title={connected ? "" : "Connect a mailbox first"} className="inline-flex items-center gap-2 h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90 disabled:opacity-50"><Plus size={16} weight="bold" /> New Email Campaign</button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle className="font-display">New Email Campaign</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Campaign name" testid="ec-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <Field label="Subject" testid="ec-subject" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} required />
          <div>
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Body</label>
            <textarea data-testid="ec-body" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} rows={5} required className="mt-1 w-full rounded-sm border border-input bg-card p-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Audience</label>
            <select data-testid="ec-audience" value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value })} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm">
              {AUDIENCES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
            {preview && <p className="text-xs text-muted-foreground mt-1" data-testid="ec-recipient-count"><Users size={12} className="inline mr-1" />{preview.count} recipient(s){preview.sample?.length ? ` — e.g. ${preview.sample.slice(0, 2).join(", ")}` : ""}</p>}
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Schedule</label>
            <div className="grid grid-cols-3 gap-2 mt-1">
              {[["now", "Send now"], ["scheduled", "Schedule"], ["recurring", "Recurring"]].map(([v, l]) => (
                <button type="button" key={v} data-testid={`ec-schedule-${v}`} onClick={() => setForm({ ...form, schedule_type: v })} className={`h-9 rounded-sm border text-sm font-medium ${form.schedule_type === v ? "border-primary bg-primary/5 text-primary" : "border-border hover:bg-accent"}`}>{l}</button>
              ))}
            </div>
          </div>
          {form.schedule_type !== "now" && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Date & time" testid="ec-datetime" type="datetime-local" value={form.scheduled_at} onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })} />
              {form.schedule_type === "recurring" && (
                <div>
                  <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Repeat</label>
                  <select data-testid="ec-recurrence" value={form.recurrence} onChange={(e) => setForm({ ...form, recurrence: e.target.value })} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm">
                    <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
                  </select>
                </div>
              )}
            </div>
          )}
          <DialogFooter><button data-testid="save-email-campaign-button" type="submit" className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">{form.schedule_type === "now" ? "Send now (mock)" : "Schedule"}</button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CampaignCard({ c, reload }) {
  const sendNow = async () => { try { const { data } = await api.post(`/email-campaigns/${c.id}/send-now`); toast.success(`Sent (mock) to ${data.recipients} recipients`); reload(); } catch (e) { toast.error(apiErr(e)); } };
  const remove = async () => { try { await api.delete(`/email-campaigns/${c.id}`); reload(); } catch (e) { toast.error(apiErr(e)); } };
  const statusColor = { sent: "bg-success/15 text-success", scheduled: "bg-primary/10 text-primary", draft: "bg-muted text-muted-foreground" }[c.status] || "bg-muted text-muted-foreground";
  return (
    <div data-testid={`email-campaign-card-${c.id}`} className="bg-card border border-border rounded-sm p-4">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <h3 className="font-display font-semibold truncate">{c.name}</h3>
          <p className="text-xs text-muted-foreground truncate">{c.subject}</p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-sm font-semibold capitalize ${statusColor}`} data-testid={`email-campaign-status-${c.id}`}>{c.status}</span>
      </div>
      <div className="text-xs text-muted-foreground mt-3 space-y-1">
        <div className="flex items-center gap-1.5">
          {c.schedule_type === "recurring" ? <ArrowsClockwise size={13} /> : c.schedule_type === "scheduled" ? <Clock size={13} /> : <PaperPlaneTilt size={13} />}
          {c.schedule_type === "recurring" ? `Recurring (${c.recurrence})` : c.schedule_type === "scheduled" ? "Scheduled" : "One-off"}
          {c.next_run_at && c.status === "scheduled" ? ` · next ${c.next_run_at.slice(0, 16).replace("T", " ")}` : ""}
        </div>
        <div>Sent: <b className="text-foreground tnum">{c.sent_count || 0}</b> · audience: {c.audience}</div>
      </div>
      <div className="flex gap-2 mt-3">
        <button data-testid={`email-send-now-${c.id}`} onClick={sendNow} className="flex-1 inline-flex items-center justify-center gap-1.5 h-8 rounded-sm border border-border text-sm font-medium hover:bg-accent"><PaperPlaneTilt size={14} /> Send now</button>
        <button data-testid={`email-delete-${c.id}`} onClick={remove} className="h-8 px-2.5 rounded-sm border border-border text-muted-foreground hover:text-destructive hover:bg-accent"><Trash size={15} /></button>
      </div>
    </div>
  );
}

function Field({ label, testid, type = "text", ...rest }) {
  return <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label><input data-testid={testid} type={type} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>;
}
