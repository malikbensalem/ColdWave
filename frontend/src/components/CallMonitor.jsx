import { useEffect, useState, useRef, useCallback } from "react";
import { toast } from "sonner";
import api from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Broadcast, PhoneX, UserSwitch, Robot, User } from "@phosphor-icons/react";

const TONE = {
  ringing: "bg-amber-100 text-amber-700", initiating: "bg-amber-100 text-amber-700",
  Initiated: "bg-amber-100 text-amber-700", Dialing: "bg-amber-100 text-amber-700",
  in_progress: "bg-emerald-100 text-emerald-700", "in-progress": "bg-emerald-100 text-emerald-700",
  answered: "bg-emerald-100 text-emerald-700", completed: "bg-secondary text-secondary-foreground",
};

// Live call monitor: real-time transcript + one-click take-over (take-over not yet wired).
export function CallMonitor({ callId, onClose }) {
  const [detail, setDetail] = useState(null);
  const bottomRef = useRef(null);

  const load = useCallback(async () => {
    if (!callId) return;
    try { const r = await api.get(`/calls/${callId}`); setDetail(r.data); } catch (e) { /* ignore */ }
  }, [callId]);

  useEffect(() => {
    if (!callId) return;
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [callId, load]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [detail?.transcript?.length]);

  const takeover = () => toast.info("Human take-over is coming soon — this button is not wired up yet.");

  return (
    <Dialog open={!!callId} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="max-w-2xl" data-testid="call-monitor-dialog">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <Broadcast size={20} weight="fill" className="text-primary" /> Listening in
            {detail && <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium capitalize ${TONE[detail.status] || "bg-secondary text-secondary-foreground"}`}>{String(detail.status || "").replace(/[-_]/g, " ")}</span>}
          </DialogTitle>
        </DialogHeader>
        <div className="text-xs text-muted-foreground -mt-1">
          {detail ? <>{detail.contact_name || detail.destination} · Voice: {detail.voice_name || "—"} · live transcript updates every 2s</> : "Connecting…"}
        </div>
        <div className="border border-border rounded-lg p-3 overflow-y-auto" style={{ maxHeight: 380, minHeight: 200 }} data-testid="monitor-transcript">
          {(!detail || (detail.transcript || []).length === 0) && <p className="text-sm text-muted-foreground">Waiting for the conversation to start…</p>}
          {(detail?.transcript || []).map((m, i) => {
            if (m.role === "system") return <div key={i} className="text-center text-xs text-muted-foreground italic my-2">{m.content}</div>;
            const isAgent = m.role === "agent";
            return (
              <div key={i} className={`flex gap-2 mb-3 ${isAgent ? "" : "flex-row-reverse"}`}>
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
        <div className="flex items-center justify-end gap-2">
          <button data-testid="monitor-takeover-button" onClick={takeover}
            className="h-9 px-3 rounded-sm bg-primary text-primary-foreground text-sm font-medium inline-flex items-center gap-1.5">
            <UserSwitch size={16} /> Take over <span className="text-[10px] opacity-75">(soon)</span>
          </button>
          <button data-testid="monitor-close-button" onClick={onClose}
            className="h-9 px-3 rounded-sm border border-border text-sm font-medium hover:bg-accent inline-flex items-center gap-1.5">
            <PhoneX size={16} /> Stop listening
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
