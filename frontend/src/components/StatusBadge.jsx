const MAP = {
  new: { label: "New", cls: "bg-secondary text-secondary-foreground border-border" },
  contacted: { label: "Contacted", cls: "bg-primary/10 text-primary border-primary/30" },
  positive: { label: "Positive", cls: "bg-success/15 text-success border-success/40" },
  callback: { label: "Callback", cls: "bg-warning/20 text-warning-foreground border-warning/50" },
  opted_out: { label: "Opted Out", cls: "bg-destructive/10 text-destructive border-destructive/40" },
  dnc: { label: "Do Not Call", cls: "bg-foreground text-background border-foreground" },
};

const SENT = {
  positive: { label: "Positive", cls: "bg-success/15 text-success border-success/40" },
  neutral: { label: "Neutral", cls: "bg-muted text-muted-foreground border-border" },
  negative: { label: "Negative", cls: "bg-destructive/10 text-destructive border-destructive/40" },
};

export function StatusBadge({ status, testid }) {
  const s = MAP[status] || MAP.new;
  const dot = status === "opted_out" || status === "dnc";
  return (
    <span data-testid={testid} className={`inline-flex items-center gap-1.5 border px-2 py-0.5 text-xs font-semibold rounded-sm ${s.cls}`}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current live-dot" />}
      {s.label}
    </span>
  );
}

export function SentimentBadge({ sentiment }) {
  if (!sentiment) return <span className="text-xs text-muted-foreground">—</span>;
  const s = SENT[sentiment] || SENT.neutral;
  return <span className={`inline-flex items-center border px-2 py-0.5 text-xs font-semibold rounded-sm ${s.cls}`}>{s.label}</span>;
}
