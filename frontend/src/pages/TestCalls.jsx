import { useEffect, useState, useRef, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { speakMock, stopSpeak } from "../lib/voice";
import { SentimentBadge } from "../components/StatusBadge";
import {
  PhoneCall, PaperPlaneRight, PhoneSlash, Robot, User, SpeakerHigh, Sparkle, ChartBar,
} from "@phosphor-icons/react";

export default function TestCalls() {
  const [scripts, setScripts] = useState([]);
  const [voices, setVoices] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [setup, setSetup] = useState({ campaign_id: "", script_id: "", voice_id: "", contact_id: "" });
  const [call, setCall] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [voiceGender, setVoiceGender] = useState("female");
  const [callMeta, setCallMeta] = useState(null);
  const endRef = useRef(null);

  const load = useCallback(async () => {
    const [s, v, c, ct] = await Promise.all([
      api.get("/scripts"), api.get("/voices"), api.get("/campaigns"), api.get("/contacts"),
    ]);
    setScripts(s.data); setVoices(v.data.voices); setCampaigns(c.data); setContacts(ct.data);
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const speak = (audioUrl, text, gender) => {
    stopSpeak();
    if (audioUrl) {
      const a = new Audio(audioUrl);
      a.play().catch(() => speakMock(text, gender));
    } else {
      speakMock(text, gender);
    }
  };

  const start = async () => {
    if (!setup.voice_id) { toast.error("Pick a voice first"); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/calls/test/start", setup);
      const v = voices.find((x) => x.id === setup.voice_id);
      setVoiceGender(v?.gender || "female");
      setCall(data);
      setCallMeta({ tts_provider: data.tts_provider, tts_error: data.tts_error, opening_meta: data.opening_meta });
      setMessages([{ role: "agent", content: data.opening }]);
      setAnalysis(null);
      if (data.tts_error) toast.error(`ElevenLabs error: ${data.tts_error}`);
      else if (data.tts_provider === "elevenlabs") toast.success("Using ElevenLabs voice");
      speak(data.audio_url, data.opening, v?.gender);
    } catch (err) { toast.error(apiErr(err)); }
    finally { setBusy(false); }
  };

  const send = async () => {
    if (!input.trim() || busy) return;
    const msg = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "prospect", content: msg }]);
    setBusy(true);
    try {
      const { data } = await api.post("/calls/test/turn", { call_id: call.call_id, message: msg });
      setMessages((m) => [...m, { role: "agent", content: data.reply }]);
      speak(data.audio_url, data.reply, voiceGender);
    } catch (err) { toast.error(apiErr(err)); }
    finally { setBusy(false); }
  };

  const end = async () => {
    stopSpeak();
    setBusy(true);
    try {
      const { data } = await api.post(`/calls/test/${call.call_id}/end`);
      setAnalysis(data.analysis);
      toast.success("Call analysed");
    } catch (err) { toast.error(apiErr(err)); }
    finally { setBusy(false); }
  };

  const reset = () => { setCall(null); setMessages([]); setAnalysis(null); setSetup({ campaign_id: "", script_id: "", voice_id: "", contact_id: "" }); };

  return (
    <div className="space-y-5 animate-fadeup" data-testid="test-calls-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Test Calls</h1>
        <p className="text-sm text-muted-foreground mt-1">Role-play with the AI agent to validate scripts before going live. You play the prospect.</p>
      </div>

      {!call ? (
        <div className="bg-card border border-border rounded-sm p-6 max-w-2xl space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold"><Sparkle size={18} weight="fill" className="text-primary" /> Configure a test call</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Sel label="Campaign (optional)" testid="setup-campaign" value={setup.campaign_id} onChange={(e) => setSetup({ ...setup, campaign_id: e.target.value })} options={campaigns.map((c) => ({ value: c.id, label: c.name }))} />
            <Sel label="Script" testid="setup-script" value={setup.script_id} onChange={(e) => setSetup({ ...setup, script_id: e.target.value })} options={scripts.map((s) => ({ value: s.id, label: s.name }))} />
            <Sel label="AI Voice *" testid="setup-voice" value={setup.voice_id} onChange={(e) => setSetup({ ...setup, voice_id: e.target.value })} options={voices.map((v) => ({ value: v.id, label: `${v.name} (${v.gender}, ${v.accent})` }))} />
            <Sel label="Link to lead (optional)" testid="setup-contact" value={setup.contact_id} onChange={(e) => setSetup({ ...setup, contact_id: e.target.value })} options={contacts.map((c) => ({ value: c.id, label: `${c.name} — ${c.company}` }))} />
          </div>
          <button data-testid="start-call-button" onClick={start} disabled={busy} className="inline-flex items-center gap-2 h-11 px-5 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90 disabled:opacity-60">
            <PhoneCall size={18} weight="fill" /> {busy ? "Connecting…" : "Start Test Call"}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 bg-card border border-border rounded-sm flex flex-col h-[60vh]">
            <div className="h-12 border-b border-border flex items-center justify-between px-4">
              <div className="flex items-center gap-2 text-sm font-medium">
                <span className="h-2 w-2 rounded-full bg-success live-dot" /> Live test · {call.voice?.name}
                <SpeakerHigh size={15} className="text-muted-foreground" />
              </div>
              <button data-testid="end-call-button" onClick={end} disabled={busy} className="inline-flex items-center gap-1.5 h-8 px-3 rounded-sm bg-destructive text-destructive-foreground text-sm font-medium hover:opacity-90"><PhoneSlash size={15} weight="fill" /> End &amp; Analyse</button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.map((m, i) => (
                <div key={i} className={`flex gap-2 ${m.role === "prospect" ? "flex-row-reverse" : ""}`}>
                  <div className={`h-7 w-7 rounded-sm flex items-center justify-center flex-shrink-0 ${m.role === "agent" ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>
                    {m.role === "agent" ? <Robot size={15} weight="bold" /> : <User size={15} weight="bold" />}
                  </div>
                  <div className={`max-w-[75%] px-3 py-2 rounded-sm text-sm ${m.role === "agent" ? "bg-accent" : "bg-primary text-primary-foreground"}`}>{m.content}</div>
                </div>
              ))}
              {busy && <div className="text-xs text-muted-foreground pl-9">AI agent is responding…</div>}
              <div ref={endRef} />
            </div>
            <div className="border-t border-border p-3 flex gap-2">
              <input data-testid="prospect-input" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder="Reply as the prospect… (e.g. 'Not interested, remove me')"
                className="flex-1 h-10 px-3 rounded-sm border border-input bg-card text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
              <button data-testid="send-message-button" onClick={send} disabled={busy} className="h-10 px-4 bg-primary text-primary-foreground rounded-sm hover:opacity-90 disabled:opacity-60"><PaperPlaneRight size={16} weight="fill" /></button>
            </div>
          </div>

          <div className="space-y-3">
            {callMeta && (
              <div className="bg-card border border-border rounded-sm p-4 text-xs space-y-1.5" data-testid="call-diagnostics">
                <div className="flex justify-between"><span className="text-muted-foreground">Voice engine</span><span className={`font-semibold ${callMeta.tts_provider === "elevenlabs" ? "text-success" : callMeta.tts_provider === "elevenlabs_error" ? "text-destructive" : ""}`}>{callMeta.tts_provider === "elevenlabs" ? "ElevenLabs" : callMeta.tts_provider === "elevenlabs_error" ? "ElevenLabs (error)" : "Browser (mock)"}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Opening mode</span><span className="font-semibold capitalize">{callMeta.opening_meta?.mode}{callMeta.opening_meta?.fallback ? " (fallback)" : ""}</span></div>
                {callMeta.opening_meta?.sources?.length > 0 && <div className="flex justify-between"><span className="text-muted-foreground">KB sources</span><span className="font-medium text-right">{callMeta.opening_meta.sources.join(", ")}</span></div>}
              </div>
            )}
            <div className="bg-card border border-border rounded-sm p-4">
              <div className="flex items-center gap-1.5 text-sm font-semibold mb-3"><ChartBar size={16} weight="bold" /> Call Analysis</div>
              {analysis ? (
                <div className="space-y-3" data-testid="call-analysis">
                  <div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">Sentiment</span><SentimentBadge sentiment={analysis.sentiment} /></div>
                  <div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">Interest score</span><span className="text-lg font-bold tnum">{analysis.score}/100</span></div>
                  <div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">Opt-out detected</span><span className={`text-xs font-semibold ${analysis.opted_out ? "text-destructive" : "text-success"}`}>{analysis.opted_out ? "YES" : "No"}</span></div>
                  <div><div className="text-xs text-muted-foreground mb-1">Summary</div><div className="text-sm">{analysis.summary}</div></div>
                  <div><div className="text-xs text-muted-foreground mb-1">Next action</div><div className="text-sm">{analysis.next_action}</div></div>
                  <button data-testid="new-call-button" onClick={reset} className="w-full h-9 mt-2 rounded-sm border border-border text-sm font-medium hover:bg-accent">New Test Call</button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">End the call to get an AI sentiment &amp; opt-out analysis. If the prospect opts out, the linked lead is auto-flagged and added to your DNC list.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Sel({ label, testid, options, ...rest }) {
  return <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label><select data-testid={testid} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><option value="">— none —</option>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>;
}
