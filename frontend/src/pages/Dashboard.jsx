import { useEffect, useState } from "react";
import api from "../lib/api";
import { StatusBadge, SentimentBadge } from "../components/StatusBadge";
import {
  Users, PhoneCall, TrendUp, ThumbsUp, Prohibit, Megaphone,
} from "@phosphor-icons/react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";

const KPIS = [
  { key: "total_contacts", label: "Total Leads", icon: Users, color: "text-primary" },
  { key: "total_calls", label: "Calls Made", icon: PhoneCall, color: "text-foreground" },
  { key: "connect_rate", label: "Connect Rate", icon: TrendUp, color: "text-primary", suffix: "%" },
  { key: "positive_responses", label: "Positive", icon: ThumbsUp, color: "text-success" },
  { key: "opt_outs", label: "Opt-outs", icon: Prohibit, color: "text-destructive" },
  { key: "active_campaigns", label: "Campaigns", icon: Megaphone, color: "text-foreground" },
];

export default function Dashboard() {
  const [stats, setStats] = useState(null);

  useEffect(() => { api.get("/dashboard/stats").then((r) => setStats(r.data)); }, []);

  if (!stats) return <Skeleton />;

  return (
    <div className="space-y-6 animate-fadeup" data-testid="dashboard-page">
      <div>
        <h1 className="font-display font-bold text-3xl tracking-tight">Control Room</h1>
        <p className="text-sm text-muted-foreground mt-1">Live overview of your outreach operation.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {KPIS.map((k) => (
          <div key={k.key} data-testid={`kpi-${k.key}`} className="bg-card border border-border rounded-sm p-4">
            <k.icon size={18} weight="bold" className={k.color} />
            <div className="mt-3 text-2xl font-bold tnum">{stats[k.key]}{k.suffix || ""}</div>
            <div className="text-xs text-muted-foreground uppercase tracking-wide mt-0.5">{k.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-card border border-border rounded-sm p-5">
          <h3 className="font-display font-semibold text-lg mb-4">Call Volume — last 7 days</h3>
          {stats.timeline.length === 0 ? (
            <EmptyChart text="No calls yet. Run a test call to populate this." />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={stats.timeline}>
                <defs>
                  <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(223 100% 33%)" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="hsl(223 100% 33%)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 32% 91%)" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Area type="monotone" dataKey="calls" stroke="hsl(223 100% 33%)" strokeWidth={2} fill="url(#g)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-card border border-border rounded-sm p-5">
          <h3 className="font-display font-semibold text-lg mb-4">Pipeline</h3>
          <div className="space-y-2.5">
            {Object.entries(stats.by_status).map(([k, v]) => {
              const total = stats.total_contacts || 1;
              return (
                <div key={k}>
                  <div className="flex justify-between items-center mb-1">
                    <StatusBadge status={k} />
                    <span className="text-sm font-bold tnum">{v}</span>
                  </div>
                  <div className="h-1.5 bg-muted rounded-sm overflow-hidden">
                    <div className="h-full bg-primary" style={{ width: `${(v / total) * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="bg-card border border-border rounded-sm p-5">
        <h3 className="font-display font-semibold text-lg mb-4">Recent Call Activity</h3>
        {stats.recent_calls.length === 0 ? (
          <EmptyChart text="No call activity yet." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
                <th className="py-2 font-semibold">Voice</th>
                <th className="py-2 font-semibold">Type</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold">Sentiment</th>
                <th className="py-2 font-semibold text-right">When</th>
              </tr>
            </thead>
            <tbody>
              {stats.recent_calls.map((c) => (
                <tr key={c.id} className="border-b border-border/60 hover:bg-muted/50">
                  <td className="py-2 font-medium">{c.voice_name || "—"}</td>
                  <td className="py-2"><span className="text-xs px-1.5 py-0.5 bg-accent rounded-sm">{c.is_test ? "Test" : "Live"}</span></td>
                  <td className="py-2 capitalize text-muted-foreground">{c.status}</td>
                  <td className="py-2"><SentimentBadge sentiment={c.sentiment} /></td>
                  <td className="py-2 text-right text-xs text-muted-foreground tnum">{(c.created_at || "").slice(11, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function EmptyChart({ text }) {
  return <div className="h-40 flex items-center justify-center text-sm text-muted-foreground border border-dashed border-border rounded-sm">{text}</div>;
}
function Skeleton() {
  return <div className="space-y-4"><div className="h-8 w-48 bg-muted rounded-sm animate-pulse" /><div className="grid grid-cols-6 gap-3">{[...Array(6)].map((_, i) => <div key={i} className="h-24 bg-muted rounded-sm animate-pulse" />)}</div></div>;
}
