import { useEffect } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import AuthCallback from "./pages/AuthCallback";
import Login from "./pages/Login";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import Campaigns from "./pages/Campaigns";
import TestCalls from "./pages/TestCalls";
import Messaging from "./pages/Messaging";
import Compliance from "./pages/Compliance";
import Settings from "./pages/Settings";

function Loader() {
  return (
    <div className="h-screen flex items-center justify-center bg-background">
      <div className="h-10 w-10 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Loader />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppRoutes() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/leads" element={<Leads />} />
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/test-calls" element={<TestCalls />} />
        <Route path="/messaging" element={<Messaging />} />
        <Route path="/compliance" element={<Compliance />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
          <Toaster position="top-right" richColors />
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
