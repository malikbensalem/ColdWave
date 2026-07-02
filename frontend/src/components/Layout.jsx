import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import api from "../lib/api";
import { applyBranding } from "../lib/branding";
import {
  ChartLineUp, Users, Megaphone, PhoneCall, ShieldCheck, Gear, SignOut, Waveform, WhatsappLogo, EnvelopeSimple, Crown, UserSwitch,
} from "@phosphor-icons/react";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: ChartLineUp, testid: "nav-dashboard", system: "dashboard" },
  { to: "/leads", label: "CRM / Leads", icon: Users, testid: "nav-leads", system: "leads" },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone, testid: "nav-campaigns", system: "campaigns" },
  { to: "/email-campaigns", label: "Email Campaigns", icon: EnvelopeSimple, testid: "nav-email-campaigns", system: "email_campaigns" },
  { to: "/test-calls", label: "Test Calls", icon: PhoneCall, testid: "nav-test-calls", system: "test_calls" },
  { to: "/messaging", label: "WhatsApp", icon: WhatsappLogo, testid: "nav-messaging", system: "whatsapp" },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck, testid: "nav-compliance", system: "compliance" },
  { to: "/settings", label: "Settings", icon: Gear, testid: "nav-settings", system: "__settings" },
];

export default function Layout() {
  const { user, logout, stopImpersonation, can, hasCap } = useAuth();
  const navigate = useNavigate();
  const [branding, setBranding] = useState(null);
  const showPlatformAdmin = hasCap("view_all_businesses");
  // Settings is visible if the user can access any settings-related area.
  const settingsVisible = ["integrations", "users", "roles", "audit"].some((s) => can(s, "read")) || true;

  useEffect(() => {
    api.get("/settings/branding").then((r) => { setBranding(r.data); applyBranding(r.data); }).catch(() => {});
  }, [user?.org_id]);

  useEffect(() => {
    const onBranding = (e) => setBranding(e.detail);
    window.addEventListener("coldwave:branding", onBranding);
    return () => window.removeEventListener("coldwave:branding", onBranding);
  }, []);

  const brandName = branding?.brand_name || "ColdWave";
  const isWhiteLabelled = !!branding?.brand_name;

  const handleStop = async () => {
    try { await stopImpersonation(); toast.success("Returned to your account"); navigate("/admin"); }
    catch { toast.error("Could not stop impersonation"); }
  };

  const visibleNav = NAV.filter((n) => (n.system === "__settings" ? settingsVisible : can(n.system, "read")));

  return (
    <div className="w-full h-screen flex overflow-hidden bg-background">
      <aside className="w-64 flex-shrink-0 border-r border-border bg-card flex flex-col">
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-border">
          {branding?.logo_url ? (
            <img src={branding.logo_url} alt={brandName} data-testid="brand-logo" className="h-8 w-8 rounded-sm object-cover" />
          ) : (
            <div className="h-8 w-8 bg-primary rounded-sm flex items-center justify-center">
              <Waveform size={20} weight="bold" className="text-primary-foreground" />
            </div>
          )}
          <div className="leading-none">
            <div className="font-display font-bold text-lg tracking-tight" data-testid="brand-name">{brandName}</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground mt-0.5">AI Calling</div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {showPlatformAdmin && (
            <NavLink
              to="/admin"
              data-testid="nav-admin"
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm font-medium transition-colors ${
                  isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground"
                }`
              }
            >
              <Crown size={18} weight="bold" />
              Platform Admin
            </NavLink>
          )}
          {visibleNav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.testid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                }`
              }
            >
              <n.icon size={18} weight="bold" />
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-border">
          <div className="flex items-center gap-3 px-2 py-2">
            <div className="h-8 w-8 rounded-sm bg-primary/10 text-primary flex items-center justify-center font-bold text-sm">
              {(user?.name || "U").charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate">{user?.name}</div>
              <div className="text-xs text-muted-foreground truncate capitalize">{user?.role}</div>
            </div>
            <button data-testid="logout-button" onClick={logout} className="text-muted-foreground hover:text-destructive transition-colors">
              <SignOut size={18} weight="bold" />
            </button>
          </div>
          {isWhiteLabelled && (
            <div data-testid="powered-by-coldwave" className="px-2 pt-1 text-[10px] text-muted-foreground/70 tracking-wide">Powered by ColdWave</div>
          )}
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {user?.impersonating && (
          <div data-testid="impersonation-banner" className="flex-shrink-0 bg-warning text-warning-foreground px-6 py-2 flex items-center justify-between text-sm font-medium">
            <span className="flex items-center gap-2">
              <UserSwitch size={16} weight="bold" />
              Impersonating <b>{user?.name}</b> ({user?.email}) — acting on behalf of {user?.org_name}
            </span>
            <button data-testid="stop-impersonation-button" onClick={handleStop} className="inline-flex items-center gap-1.5 h-7 px-3 rounded-sm bg-foreground text-background text-xs font-semibold hover:opacity-90">
              <SignOut size={13} weight="bold" /> Stop impersonating
            </button>
          </div>
        )}
        <header className="h-16 flex-shrink-0 border-b border-border bg-card flex items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Workspace</span>
            <span data-testid="org-name" className="text-sm font-semibold">{user?.org_name}</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="h-2 w-2 rounded-full bg-success live-dot" />
            UK Compliance Active
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
