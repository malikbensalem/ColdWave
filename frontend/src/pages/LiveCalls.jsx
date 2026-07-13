import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Broadcast, PhoneCall, PhoneX, UserSwitch, Robot, User, ArrowsClockwise } from "@phosphor-icons/react";

const STATUS_TONE = {
  ringing: "bg-amber-100 text-amber-700", initiating: "bg-amber-100 text-amber-700",
  in_progress: "bg-emerald-100 text-emerald-700", "in-progress": "bg-emerald-100 text-emerald-700",
  answered: "bg-emerald-100 text-emerald-700",
};

function StatusBadge({ status }) {
  const tone = STATUS_TONE[status] || "bg-secondary text-secondary-foreground";
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium capitalize ${tone}`}>{(status || "").replace(/[-_]/g, " ")}</span>;
}

export default function LiveCalls() {
  const [calls, setCalls] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [takeoverOpen, setTakeoverOpen] = useState(false);
  const [humanNumber, setHumanNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/calls/live/active");
      setCalls(r.data || []);
      if (!selectedId && r.data?.length) setSelectedId(r.data[0].id);
    } catch (e) { /* silent poll */ }
    finally { setLoading(false); }
  }, [selectedId]);

  const loadDetail = useCallback(async (id) => {
    if (!id) { setDetail(null); return; }
    try { const r = await api.get(`/calls/${id}`); setDetail(r.data); } catch (e) { /* ignore */ }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);
  useEffect(() => { loadDetail(selectedId); const t = setInterval(() => loadDetail(selectedId), 2000); return () => clearInterval(t); }, [selectedId, loadDetail]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [detail?.transcript?.length]);

  const takeover = async () => {
    if (!humanNumber.trim()) { toast.error("Enter a phone number to connect the human agent."); return; }
    setBusy(true);
    try {
      await api.post(`/calls/${selectedId}/takeover`, { human_number: humanNumber.trim() });
      toast.success("Handing the call over to a human…");
      setTakeoverOpen(false); setHumanNumber(""); loadDetail(selectedId);
    } catch (e) { toast.error(apiErr(e)); }
    finally { setBusy(false); }
  };

  const hangup = async () => {
    setBusy(true);
    try { await api.post(`/calls/${selectedId}/hangup`); toast.success("Call ended."); load(); }
    catch (e) { toast.error(apiErr(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-5 animate-fadeup" data-testid="live-calls-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display font-bold text-3xl tracking-tight flex items-center gap-2">
            <Broadcast size={28} weight="fill" className="text-primary" /> Live Calls
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Monitor active AI calls in real time, listen to the transcript, and take over instantly.</p>
        </div>
        <button data-testid="refresh-live-calls" onClick={load} className="h-9 px-3 rounded-sm border border-border text-sm font-medium hover:bg-accent inline-flex items-center gap-1.5">
          <ArrowsClockwise size={15} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Active calls list */}
        <div className="lg:col-span-1 space-y-2" data-testid="live-calls-list">
          {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {!loading && calls.length === 0 && (
            <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground" data-testid="no-live-calls">
              No live calls right now. Start a campaign or dial a lead to see it here.
            </div>
          )}
          {calls.map((c) => (
            <button key={c.id} data-testid={`live-call-${c.id}`} onClick={() => setSelectedId(c.id)}
              className={`w-full text-left rounded-lg border p-3 transition-colors ${selectedId === c.id ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-accent"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-sm truncate">{c.contact_name || c.destination || "Unknown"}</span>
                <StatusBadge status={c.status} />
              </div>
              <div className="flex items-center justify-between mt-1 text-xs text-muted-foreground">
                <span>{c.destination}</span>
                <span className="uppercase tracking-wide">{c.provider}{c.handoff ? " · handed over" : ""}</span>
              </div>
            </button>
          ))}
        </div>

        {/* Live transcript + controls */}
        <div className="lg:col-span-2">
          {!detail && <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">Select a live call to monitor.</div>}
          {detail && (
            <div className="rounded-lg border border-border bg-card flex flex-col" style={{ minHeight: 420 }} data-testid="live-transcript-panel">
              <div className="flex items-center justify-between p-4 border-b border-border">
                <div>
                  <div className="font-semibold flex items-center gap-2">{detail.contact_name || detail.destination}<StatusBadge status={detail.status} /></div>
                  <div className="text-xs text-muted-foreground mt-0.5">{detail.destination} · Voice: {detail.voice_name || "—"} {detail.handoff && "· 🔴 Human took over"}</div>
                </div>
                <div className="flex items-center gap-2">
                  <button data-testid="takeover-button" disabled={busy || detail.handoff} onClick={() => setTakeoverOpen(true)}
                    className="h-9 px-3 rounded-sm bg-primary text-primary-foreground text-sm font-medium inline-flex items-center gap-1.5 disabled:opacity-50">
                    <UserSwitch size={16} /> Take over
                  </button>
                  <button data-testid="hangup-button" disabled={busy} onClick={hangup}
                    className="h-9 px-3 rounded-sm border border-destructive text-destructive text-sm font-medium inline-flex items-center gap-1.5 hover:bg-destructive/10 disabled:opacity-50">
                    <PhoneX size={16} /> End
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3" data-testid="transcript-stream" style={{ maxHeight: 460 }}>
                {(detail.transcript || []).length === 0 && <p className="text-sm text-muted-foreground">Waiting for the conversation to start…</p>}
                {(detail.transcript || []).map((m, i) => {
                  const isAgent = m.role === "agent";
                  const isSys = m.role === "system";
                  if (isSys) return <div key={i} className="text-center text-xs text-muted-foreground italic">{m.content}</div>;
                  return (
                    <div key={i} className={`flex gap-2 ${isAgent ? "" : "flex-row-reverse"}`}>
                      <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center ${isAgent ? "bg-primary/15 text-primary" : "bg-secondary text-secondary-foreground"}`}>
                        {isAgent ? <Robot size={15} /> : <User size={15} />}
                      </div>
                      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${isAgent ? "bg-primary/10" : "bg-secondary"}`}>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">{isAgent ? "AI Agent" : "Prospect"}</div>
                        {m.content}
                      </div>
                    </div>
                  );
                })}
                <div ref={bottomRef} />
              </div>
            </div>
          )}
        </div>
      </div>

      <Dialog open={takeoverOpen} onOpenChange={setTakeoverOpen}>
        <DialogContent data-testid="takeover-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><UserSwitch size={20} className="text-primary" /> Take over this call</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Enter the phone number to ring — we'll stop the AI and connect the prospect to that human agent.</p>
            <input data-testid="takeover-number-input" value={humanNumber} onChange={(e) => setHumanNumber(e.target.value)} placeholder="+441234567890"
              className="w-full h-10 px-3 rounded-sm border border-border bg-background text-sm" />
          </div>
          <DialogFooter>
            <button onClick={() => setTakeoverOpen(false)} className="h-9 px-3 rounded-sm border border-border text-sm font-medium hover:bg-accent">Cancel</button>
            <button data-testid="confirm-takeover-button" disabled={busy} onClick={takeover}
              className="h-9 px-4 rounded-sm bg-primary text-primary-foreground text-sm font-medium inline-flex items-center gap-1.5 disabled:opacity-50">
              <PhoneCall size={16} /> Connect human
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
