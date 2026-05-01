import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth, AUTH_QUERY_KEY } from "./hooks/useAuth";
import { api } from "./api/client";
import { Layout } from "./components/Layout";
import { ToastHost } from "./components/ToastHost";
import { LoginPage } from "./pages/LoginPage";
import { ConversationsPage } from "./pages/ConversationsPage";
import { ConversationViewerPage } from "./pages/ConversationViewerPage";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";

function LoginRedirect() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useEffect(() => {
    const hash = window.location.hash;
    if (!hash.includes("access_token=")) return;
    const params = new URLSearchParams(hash.replace(/^#/, ""));
    const token = params.get("access_token");
    const refresh = params.get("refresh_token");
    if (!token) return;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    localStorage.setItem("access_token", token);
    if (refresh) localStorage.setItem("refresh_token", refresh);
    else localStorage.removeItem("refresh_token");
    api.defaults.headers.common.Authorization = `Bearer ${token}`;
    void queryClient.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    navigate("/", { replace: true });
  }, [navigate, queryClient]);

  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <div style={{ padding: "2rem", textAlign: "center" }}>Loading…</div>;
  if (isAuthenticated) return <Navigate to="/" replace />;
  return <LoginPage />;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <div style={{ padding: "2rem", textAlign: "center" }}>Loading…</div>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRedirect />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<ConversationsPage />} />
        <Route path="conversations/:id" element={<ConversationViewerPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <ToastHost />
      <AppRoutes />
    </BrowserRouter>
  );
}
