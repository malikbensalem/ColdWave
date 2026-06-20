import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import { apiErr } from "../lib/api";
import { Waveform, GoogleLogo, MicrosoftOutlookLogo, ShieldCheck } from "@phosphor-icons/react";

export default function Login() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", name: "", org_name: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) navigate("/dashboard", { replace: true });
  }, [user, navigate]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    if (e) e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        await login(form.email, form.password);
      } else {
        await register(form);
      }
      navigate("/dashboard", { replace: true });
    } catch (err) {
      toast.error(apiErr(err));
    } finally {
      setBusy(false);
    }
  };

  const googleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen flex">
      {/* Left brand panel */}
      <div className="hidden lg:flex w-[44%] bg-primary text-primary-foreground flex-col justify-between p-12 relative overflow-hidden">
        <div className="flex items-center gap-3 relative z-10">
          <div className="h-10 w-10 bg-primary-foreground rounded-sm flex items-center justify-center">
            <Waveform size={24} weight="bold" className="text-primary" />
          </div>
          <span className="font-display font-bold text-2xl">ColdWave</span>
        </div>
        <div className="relative z-10">
          <h1 className="font-display font-bold text-5xl leading-[1.05] tracking-tight">
            Compliant AI<br />cold calling,<br />at scale.
          </h1>
          <p className="mt-6 text-primary-foreground/80 text-base max-w-md leading-relaxed">
            Realistic male & female AI voices, 3CX integration, a built-in CRM, and UK TPS / GDPR
            compliance baked in. Multi-tenant by design.
          </p>
          <div className="mt-8 flex items-center gap-2 text-sm text-primary-foreground/90">
            <ShieldCheck size={20} weight="bold" /> UK Cold-Calling Law &amp; GDPR enforced
          </div>
        </div>
        <div className="text-xs text-primary-foreground/50 relative z-10">© 2026 ColdWave. For lawful B2B outreach.</div>
        <div className="absolute -right-24 -bottom-24 h-96 w-96 rounded-full bg-primary-foreground/5" />
        <div className="absolute right-10 top-20 h-48 w-48 rounded-full bg-primary-foreground/5" />
      </div>

      {/* Right form */}
      <div className="flex-1 flex items-center justify-center p-6 bg-background">
        <div className="w-full max-w-sm animate-fadeup">
          <h2 className="font-display font-bold text-3xl tracking-tight">
            {mode === "login" ? "Welcome back" : "Create your workspace"}
          </h2>
          <p className="text-sm text-muted-foreground mt-1.5 mb-6">
            {mode === "login" ? "Sign in to your ColdWave account." : "Start a new multi-tenant organisation."}
          </p>

          <div className="space-y-2 mb-4">
            <button data-testid="google-login-button" onClick={googleLogin}
              className="w-full flex items-center justify-center gap-2 border border-border bg-card h-11 rounded-sm text-sm font-medium hover:bg-accent transition-colors">
              <GoogleLogo size={18} weight="bold" /> Continue with Google
            </button>
            <button data-testid="o365-login-button"
              onClick={() => toast.info("Office 365 SSO: admins configure Azure AD in Settings → Integrations first.")}
              className="w-full flex items-center justify-center gap-2 border border-border bg-card h-11 rounded-sm text-sm font-medium hover:bg-accent transition-colors">
              <MicrosoftOutlookLogo size={18} weight="bold" /> Continue with Office 365
            </button>
          </div>

          <div className="flex items-center gap-3 my-5">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs uppercase tracking-widest text-muted-foreground">or</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <form onSubmit={submit} className="space-y-3">
            {mode === "register" && (
              <>
                <Field testid="name-input" label="Your name" value={form.name} onChange={set("name")} required />
                <Field testid="org-input" label="Organisation name" value={form.org_name} onChange={set("org_name")} required />
              </>
            )}
            <Field testid="email-input" label="Work email" type="email" value={form.email} onChange={set("email")} required />
            <Field testid="password-input" label="Password" type="password" value={form.password} onChange={set("password")} required />
            <button data-testid="submit-auth-button" disabled={busy} type="button" onClick={submit}
              className="w-full h-11 bg-primary text-primary-foreground rounded-sm font-medium text-sm hover:opacity-90 active:scale-[0.99] transition-all disabled:opacity-60">
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create workspace"}
            </button>
          </form>

          <p className="text-sm text-muted-foreground mt-5 text-center">
            {mode === "login" ? "New to ColdWave?" : "Already have an account?"}{" "}
            <button data-testid="toggle-auth-mode" onClick={() => setMode(mode === "login" ? "register" : "login")}
              className="text-primary font-medium hover:underline">
              {mode === "login" ? "Create a workspace" : "Sign in"}
            </button>
          </p>

          {mode === "login" && (
            <div className="mt-6 p-3 bg-accent rounded-sm text-xs text-muted-foreground">
              <span className="font-semibold text-foreground">Demo admin:</span> admin@coldwave.ai / Admin123!
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, testid, type = "text", ...rest }) {
  return (
    <div>
      <label className="text-xs uppercase tracking-[0.15em] font-semibold text-muted-foreground">{label}</label>
      <input data-testid={testid} type={type} {...rest}
        className="mt-1.5 flex h-11 w-full rounded-sm border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
    </div>
  );
}
