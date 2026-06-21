import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import {
  ChartLineUp, Users, Megaphone, PhoneCall, ShieldCheck, Gear, SignOut, Waveform, WhatsappLogo,
} from "@phosphor-icons/react";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: ChartLineUp, testid: "nav-dashboard" },
  { to: "/leads", label: "CRM / Leads", icon: Users, testid: "nav-leads" },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone, testid: "nav-campaigns" },
  { to: "/test-calls", label: "Test Calls", icon: PhoneCall, testid: "nav-test-calls" },
  { to: "/messaging", label: "WhatsApp", icon: WhatsappLogo, testid: "nav-messaging" },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck, testid: "nav-compliance" },
  { to: "/settings", label: "Settings", icon: Gear, testid: "nav-settings" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="w-full h-screen flex overflow-hidden bg-background">
      <aside className="w-64 flex-shrink-0 border-r border-border bg-card flex flex-col">
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-border">
          <div className="h-8 w-8 bg-primary rounded-sm flex items-center justify-center">
            <Waveform size={20} weight="bold" className="text-primary-foreground" />
          </div>
          <div className="leading-none">
            <div className="font-display font-bold text-lg tracking-tight">ColdWave</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground mt-0.5">AI Calling</div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV.map((n) => (
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
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
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
