import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import api, { apiErr } from "../lib/api";
import { speakMock, stopSpeak } from "../lib/voice";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import {
  Plus, Sparkle, SpeakerHigh, Stop, Megaphone, FileText, MicrophoneStage, Trash, GenderMale, GenderFemale,
} from "@phosphor-icons/react";

export default function Campaigns() {
  return (
    <div className="space-y-5 animate-fadeup" data-testid="campaigns-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Campaigns &amp; Scripts</h1>
        <p className="text-sm text-muted-foreground mt-1">Build campaigns, craft AI scripts, and choose your voice.</p>
      </div>
      <Tabs defaultValue="campaigns">
        <TabsList>
          <TabsTrigger value="campaigns" data-testid="tab-campaigns"><Megaphone size={16} className="mr-1.5" />Campaigns</TabsTrigger>
          <TabsTrigger value="scripts" data-testid="tab-scripts"><FileText size={16} className="mr-1.5" />Scripts</TabsTrigger>
          <TabsTrigger value="voices" data-testid="tab-voices"><MicrophoneStage size={16} className="mr-1.5" />Voices</TabsTrigger>
        </TabsList>
        <TabsContent value="campaigns" className="mt-4"><CampaignsTab /></TabsContent>
        <TabsContent value="scripts" className="mt-4"><ScriptsTab /></TabsContent>
        <TabsContent value="voices" className="mt-4"><VoicesTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function CampaignsTab() {
  const [items, setItems] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [voices, setVoices] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", script_id: "", voice_id: "" });

  const load = useCallback(async () => {
    const [c, s, v] = await Promise.all([api.get("/campaigns"), api.get("/scripts"), api.get("/voices")]);
    setItems(c.data); setScripts(s.data); setVoices(v.data.voices);
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e.preventDefault();
    try { await api.post("/campaigns", form); toast.success("Campaign created"); setOpen(false); setForm({ name: "", description: "", script_id: "", voice_id: "" }); load(); }
    catch (err) { toast.error(apiErr(err)); }
  };
  const toggle = async (c) => { await api.put(`/campaigns/${c.id}`, { status: c.status === "active" ? "paused" : "active" }); load(); };
  const remove = async (id) => { await api.delete(`/campaigns/${id}`); load(); };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <button data-testid="create-campaign-button" className="inline-flex items-center gap-2 h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><Plus size={16} weight="bold" /> New Campaign</button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle className="font-display">New Campaign</DialogTitle></DialogHeader>
            <form onSubmit={create} className="space-y-3">
              <Field label="Campaign name" testid="campaign-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <Field label="Description" testid="campaign-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              <Sel label="Script" testid="campaign-script" value={form.script_id} onChange={(e) => setForm({ ...form, script_id: e.target.value })} options={scripts.map((s) => ({ value: s.id, label: s.name }))} />
              <Sel label="AI Voice" testid="campaign-voice" value={form.voice_id} onChange={(e) => setForm({ ...form, voice_id: e.target.value })} options={voices.map((v) => ({ value: v.id, label: `${v.name} (${v.gender}, ${v.accent})` }))} />
              <DialogFooter><button data-testid="save-campaign-button" type="submit" className="h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium">Create</button></DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((c) => (
          <div key={c.id} data-testid={`campaign-card-${c.id}`} className="bg-card border border-border rounded-sm p-4">
            <div className="flex justify-between items-start">
              <h3 className="font-display font-semibold text-lg">{c.name}</h3>
              <span className={`text-xs px-2 py-0.5 rounded-sm font-semibold capitalize ${c.status === "active" ? "bg-success/15 text-success" : "bg-muted text-muted-foreground"}`}>{c.status}</span>
            </div>
            <p className="text-sm text-muted-foreground mt-1 min-h-[20px]">{c.description}</p>
            <div className="text-xs text-muted-foreground mt-3 tnum">{c.call_count} calls logged</div>
            <div className="flex gap-2 mt-3">
              <button data-testid={`toggle-campaign-${c.id}`} onClick={() => toggle(c)} className="flex-1 h-8 rounded-sm border border-border text-sm font-medium hover:bg-accent">{c.status === "active" ? "Pause" : "Activate"}</button>
              <button onClick={() => remove(c.id)} className="h-8 px-2.5 rounded-sm border border-border text-muted-foreground hover:bg-accent"><Trash size={15} /></button>
            </div>
          </div>
        ))}
        {items.length === 0 && <Empty text="No campaigns yet — create one to get started." />}
      </div>
    </div>
  );
}

function ScriptsTab() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [scriptType, setScriptType] = useState("line_by_line");
  const [form, setForm] = useState({ name: "", content: "", objective: "", personality: "" });
  const [gen, setGen] = useState({ product: "", audience: "", objective: "", tone: "professional and friendly", personality: "" });
  const [genBusy, setGenBusy] = useState(false);

  const load = useCallback(async () => { const { data } = await api.get("/scripts"); setItems(data); }, []);
  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    if (!gen.product) { toast.error("Describe your product first"); return; }
    setGenBusy(true);
    try {
      const { data } = await api.post("/scripts/generate", { ...gen, script_type: scriptType });
      if (scriptType === "personality") setForm({ ...form, personality: data.content, objective: gen.objective });
      else setForm({ ...form, content: data.content, objective: gen.objective });
      toast.success(scriptType === "personality" ? "AI persona generated" : "AI script generated");
    }
    catch (err) { toast.error(apiErr(err)); }
    finally { setGenBusy(false); }
  };
  const save = async (e) => {
    e.preventDefault();
    try {
      await api.post("/scripts", { ...form, script_type: scriptType });
      toast.success("Saved"); setOpen(false);
      setForm({ name: "", content: "", objective: "", personality: "" });
      load();
    } catch (err) { toast.error(apiErr(err)); }
  };
  const remove = async (id) => { await api.delete(`/scripts/${id}`); load(); };

  const isPersona = scriptType === "personality";

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild><button data-testid="create-script-button" className="inline-flex items-center gap-2 h-10 px-4 bg-primary text-primary-foreground rounded-sm text-sm font-medium hover:opacity-90"><Plus size={16} weight="bold" /> New Script</button></DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader><DialogTitle className="font-display">New Script</DialogTitle></DialogHeader>

            <div className="grid grid-cols-2 gap-2 mb-1">
              <button type="button" data-testid="script-type-line" onClick={() => setScriptType("line_by_line")}
                className={`text-left p-2.5 rounded-sm border text-sm ${!isPersona ? "border-primary bg-primary/5" : "border-border hover:bg-accent"}`}>
                <div className="font-semibold">Line-by-line script</div>
                <div className="text-xs text-muted-foreground">Exact lines + responses. Still answers off-script questions from your company overview.</div>
              </button>
              <button type="button" data-testid="script-type-personality" onClick={() => setScriptType("personality")}
                className={`text-left p-2.5 rounded-sm border text-sm ${isPersona ? "border-primary bg-primary/5" : "border-border hover:bg-accent"}`}>
                <div className="font-semibold">Personality-driven</div>
                <div className="text-xs text-muted-foreground">Give the agent a persona; it generates a unique conversation.</div>
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2 bg-accent p-3 rounded-sm">
                <div className="flex items-center gap-1.5 text-sm font-semibold"><Sparkle size={16} weight="fill" className="text-primary" /> AI Generator</div>
                <Field label="Product / service" testid="gen-product" value={gen.product} onChange={(e) => setGen({ ...gen, product: e.target.value })} />
                <Field label="Target audience" testid="gen-audience" value={gen.audience} onChange={(e) => setGen({ ...gen, audience: e.target.value })} />
                <Field label="Call objective" testid="gen-objective" value={gen.objective} onChange={(e) => setGen({ ...gen, objective: e.target.value })} />
                <Field label={isPersona ? "Personality / tone (e.g. warm, witty, consultative)" : "Tone"} testid="gen-personality" value={isPersona ? gen.personality : gen.tone} onChange={(e) => setGen({ ...gen, [isPersona ? "personality" : "tone"]: e.target.value })} />
                <button data-testid="generate-script-button" onClick={generate} disabled={genBusy} className="w-full h-9 bg-primary text-primary-foreground rounded-sm text-sm font-medium disabled:opacity-60">{genBusy ? "Generating…" : (isPersona ? "Generate Persona" : "Generate Script")}</button>
              </div>
              <form onSubmit={save} className="space-y-2">
                <Field label="Script name" testid="script-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                {isPersona ? (
                  <div>
                    <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Persona &amp; behaviour</label>
                    <textarea data-testid="script-personality" value={form.personality} onChange={(e) => setForm({ ...form, personality: e.target.value })} rows={10}
                      className="mt-1 w-full rounded-sm border border-input bg-card p-2.5 text-xs font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" required />
                  </div>
                ) : (
                  <div>
                    <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">Script (line by line)</label>
                    <textarea data-testid="script-content" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} rows={10}
                      className="mt-1 w-full rounded-sm border border-input bg-card p-2.5 text-xs font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" required />
                  </div>
                )}
                <button data-testid="save-script-button" type="submit" className="w-full h-9 bg-foreground text-background rounded-sm text-sm font-medium">Save Script</button>
              </form>
            </div>
          </DialogContent>
        </Dialog>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {items.map((s) => (
          <div key={s.id} data-testid={`script-card-${s.id}`} className="bg-card border border-border rounded-sm p-4">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-display font-semibold">{s.name}</h3>
                <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 bg-accent rounded-sm font-semibold">{s.script_type === "personality" ? "Personality" : "Line-by-line"}</span>
              </div>
              <button onClick={() => remove(s.id)} className="text-muted-foreground hover:text-destructive"><Trash size={15} /></button>
            </div>
            <pre className="mt-2 text-[11px] font-mono text-muted-foreground whitespace-pre-wrap line-clamp-6 max-h-32 overflow-hidden">{s.script_type === "personality" ? s.personality : s.content}</pre>
          </div>
        ))}
        {items.length === 0 && <Empty text="No scripts yet — generate one with AI." />}
      </div>
    </div>
  );
}

function VoicesTab() {
  const [voices, setVoices] = useState([]);
  const [enabled, setEnabled] = useState(false);
  const [playing, setPlaying] = useState(null);
  const SAMPLE = "Hello, this is Alex calling from ColdWave. Have I caught you at a good time?";

  useEffect(() => { api.get("/voices").then((r) => { setVoices(r.data.voices); setEnabled(r.data.elevenlabs_enabled); }); }, []);

  const preview = async (v) => {
    if (playing === v.id) { stopSpeak(); setPlaying(null); return; }
    setPlaying(v.id);
    try {
      const { data } = await api.post("/voices/preview", { voice_id: v.id, text: SAMPLE });
      if (data.mock || !data.audio_url) {
        speakMock(SAMPLE, v.gender);
        toast.info("Mock preview (browser voice). Add an ElevenLabs key in Settings for studio audio.");
      } else {
        const audio = new Audio(data.audio_url);
        audio.onended = () => setPlaying(null);
        audio.play();
        return;
      }
    } catch (e) { toast.error("Preview failed"); }
    setTimeout(() => setPlaying(null), 4000);
  };

  return (
    <div className="space-y-4">
      {!enabled && <div className="text-xs bg-warning/15 border border-warning/40 text-warning-foreground rounded-sm p-2.5">ElevenLabs is in <b>mock mode</b> — previews use your browser's voice. Add an API key in Settings → Integrations for realistic studio audio.</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {voices.map((v) => (
          <div key={v.id} data-testid={`voice-card-${v.id}`} className="bg-card border border-border rounded-sm p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {v.gender === "male" ? <GenderMale size={18} className="text-primary" weight="bold" /> : <GenderFemale size={18} className="text-destructive" weight="bold" />}
                <span className="font-display font-semibold text-lg">{v.name}</span>
              </div>
              <span className="text-xs px-2 py-0.5 bg-accent rounded-sm">{v.accent}</span>
            </div>
            <p className="text-sm text-muted-foreground mt-2 min-h-[40px]">{v.description}</p>
            <button data-testid={`preview-voice-${v.id}`} onClick={() => preview(v)} className="mt-2 w-full inline-flex items-center justify-center gap-2 h-9 rounded-sm border border-border text-sm font-medium hover:bg-accent">
              {playing === v.id ? <><Stop size={15} weight="fill" /> Stop</> : <><SpeakerHigh size={15} weight="fill" /> Preview voice</>}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({ label, testid, ...rest }) {
  return <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label><input data-testid={testid} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>;
}
function Sel({ label, testid, options, ...rest }) {
  return <div><label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label><select data-testid={testid} {...rest} className="mt-1 flex h-10 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><option value="">— select —</option>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></div>;
}
function Empty({ text }) { return <div className="col-span-full py-10 text-center text-sm text-muted-foreground border border-dashed border-border rounded-sm">{text}</div>; }
