import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { Role } from "./api/types";
import { AuthProvider, useAuth } from "./auth";
import { ChatPage } from "./pages/ChatPage";
import { ConsolePage } from "./pages/ConsolePage";
import { LoginPage } from "./pages/LoginPage";

function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={user.role === "agent" ? "/console" : "/chat"} replace />;
  return children;
}

function Home() {
  const { user, ready } = useAuth();
  if (!ready) return null;
  return <Navigate to={!user ? "/login" : user.role === "agent" ? "/console" : "/chat"} replace />;
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/chat"
            element={
              <RequireRole role="customer">
                <ChatPage />
              </RequireRole>
            }
          />
          <Route
            path="/console"
            element={
              <RequireRole role="agent">
                <ConsolePage />
              </RequireRole>
            }
          />
          <Route path="*" element={<Home />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
