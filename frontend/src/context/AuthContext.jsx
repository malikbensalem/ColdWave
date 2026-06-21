import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { apiErr, setToken } from "../lib/api";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    checkAuth();
  }, [checkAuth]);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    if (data.access_token) setToken(data.access_token);
    setUser(data);
    return data;
  };

  const register = async (payload) => {
    const { data } = await api.post("/auth/register", payload);
    if (data.access_token) setToken(data.access_token);
    setUser(data);
    return data;
  };

  const applyAuth = (data) => {
    if (data?.access_token) setToken(data.access_token);
    setUser(data);
  };

  const impersonate = async (userId) => {
    const { data } = await api.post("/auth/impersonate", { user_id: userId });
    if (data.access_token) setToken(data.access_token);
    setUser(data);
    return data;
  };

  const stopImpersonation = async () => {
    const { data } = await api.post("/auth/stop-impersonation");
    if (data.access_token) setToken(data.access_token);
    setUser(data);
    return data;
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    setToken(null);
    setUser(false);
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider value={{ user, setUser, applyAuth, loading, login, register, logout, checkAuth, impersonate, stopImpersonation, apiErr }}>
      {children}
    </AuthContext.Provider>
  );
}
