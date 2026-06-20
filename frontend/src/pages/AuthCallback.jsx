import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../context/AuthContext";

export default function AuthCallback() {
  const navigate = useNavigate();
  const { applyAuth } = useAuth();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const hash = window.location.hash || "";
    const sid = new URLSearchParams(hash.replace("#", "")).get("session_id");
    if (!sid) { navigate("/login"); return; }
    (async () => {
      try {
        const { data } = await api.post("/auth/google/session", { session_id: sid });
        applyAuth(data);
        window.history.replaceState(null, "", "/dashboard");
        navigate("/dashboard", { replace: true });
      } catch {
        navigate("/login");
      }
    })();
  }, [navigate, applyAuth]);

  return (
    <div className="h-screen flex items-center justify-center bg-background">
      <div className="text-center">
        <div className="h-10 w-10 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-sm text-muted-foreground">Signing you in…</p>
      </div>
    </div>
  );
}
