import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { WhatsappLogo, PaperPlaneRight, ArrowClockwise, Warning } from "@phosphor-icons/react";

const STATE_CLS = {
  queued: "bg-muted text-muted-foreground",
  sent: "bg-primary/10 text-primary",
  delivered: "bg-success/15 text-success",
  failed: "bg-destructive/10 text-destructive",
  received: "bg-accent text-foreground",
};

export default function Messaging() {
  const [messages, setMessages] = useState([]);
  const [dead, setDead] = useState([]);
  const [form, setForm] = useState({ to: "", body: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [m, d] = await Promise.all([api.get("/messages"), api.get("/messages/dead-letters")]);
    setMessages(m.data); setDead(d.data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const send = async (e) => {
    e.preventDefault();
    if (!form.to || !form.body) return;
    setBusy(true);
    try {
      const { data } = await api.post("/messages/whatsapp/send", form);
      toast.success(`WhatsApp ${data.state}${data.mock ? " (mock)" : ""}`);
      setForm({ to: "", body: "" });
      load();
    } catch (err) { toast.error(apiErr(err)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-5 animate-fadeup" data-testid="messaging-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display font-bold text-3xl tracking-tight">Messaging · WhatsApp</h1>
          <p className="text-sm text-muted-foreground mt-1">Outbound &amp; inbound WhatsApp with delivery tracking. DNC-protected.</p>
        </div>
        <button data-testid="refresh-messages" onClick={load} className="inline-flex items-center gap-1.5 h-10 px-3 rounded-sm border border-border text-sm font-medium hover:bg-accent"><ArrowClockwise size={15} weight="bold" /> Refresh</button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <form onSubmit={send} className="bg-card border border-border rounded-sm p-5 space-y-3 h-fit">
          <div className="flex items-center gap-2 font-display font-semibold"><WhatsappLogo size={20} weight="fill" className="text-success" /> New WhatsApp</div>
          <div>
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">To (E.164)</label>
            <input data-testid="wa-to" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} placeholder="+447700900123"
              className="mt-1 h-10 w-full rounded-sm border border-input bg-card px-3 text-sm tnum focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Message</label>
            <textarea data-testid="wa-body" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} rows={4}
              className="mt-1 w-full rounded-sm border border-input bg-card p-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </div>
          <button data-testid="wa-send" disabled={busy} type="submit" className="w-full inline-flex items-center justify-center gap-2 h-10 bg-success text-success-foreground rounded-sm text-sm font-medium hover:opacity-90 disabled:opacity-60">
            <PaperPlaneRight size={15} weight="fill" /> {busy ? "Sending…" : "Send"}
          </button>
          <p className="text-xs text-muted-foreground">Runs in MOCK mode until WhatsApp credentials are added in Settings → Integrations.</p>
        </form>

        <div className="lg:col-span-2">
          <Tabs defaultValue="all">
            <TabsList>
              <TabsTrigger value="all" data-testid="tab-all-messages">Messages</TabsTrigger>
              <TabsTrigger value="dead" data-testid="tab-dead-letters"><Warning size={15} className="mr-1" />Failures ({dead.length})</TabsTrigger>
            </TabsList>
            <TabsContent value="all" className="mt-3">
              <div className="bg-card border border-border rounded-sm overflow-hidden">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border bg-secondary/50"><th className="py-2.5 px-4 font-semibold">Dir</th><th className="py-2.5 px-4 font-semibold">To/From</th><th className="py-2.5 px-4 font-semibold">Body</th><th className="py-2.5 px-4 font-semibold">State</th></tr></thead>
                  <tbody>
                    {messages.map((m) => (
                      <tr key={m.id} data-testid={`message-row-${m.id}`} className="border-b border-border/60 hover:bg-muted/50">
                        <td className="py-2.5 px-4 text-xs capitalize">{m.direction}</td>
                        <td className="py-2.5 px-4 tnum text-xs">{m.to || m.from}</td>
                        <td className="py-2.5 px-4 max-w-[260px] truncate">{m.body}</td>
                        <td className="py-2.5 px-4"><span className={`text-xs px-2 py-0.5 rounded-sm font-semibold capitalize ${STATE_CLS[m.state] || "bg-muted"}`}>{m.state}</span></td>
                      </tr>
                    ))}
                    {messages.length === 0 && <tr><td colSpan={4} className="py-8 text-center text-muted-foreground text-sm">No messages yet.</td></tr>}
                  </tbody>
                </table>
              </div>
            </TabsContent>
            <TabsContent value="dead" className="mt-3">
              <div className="bg-card border border-border rounded-sm p-4 space-y-2">
                {dead.length ? dead.map((d) => (
                  <div key={d.id} className="border border-destructive/30 rounded-sm p-2.5 text-sm">
                    <div className="flex justify-between"><span className="tnum text-xs">{d.to}</span><span className="text-xs text-muted-foreground">{(d.created_at || "").slice(0, 16)}</span></div>
                    <div className="text-xs text-destructive mt-1">{d.error}</div>
                  </div>
                )) : <div className="text-sm text-muted-foreground">No failed messages.</div>}
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
