import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { AdminPage } from "./pages/AdminPage";
import { LoginPage } from "./pages/LoginPage";
import { MePage } from "./pages/MePage";
import { Shell } from "./Shell";
import "./theme.css";
import { TooltipProvider } from "./ui/Tooltip";

function RequireLogin({ admin, children }: { admin?: boolean; children: ReactNode }) {
  const { account, checking } = useAuth();
  if (checking) return <div className="loading">Checking your sign-in…</div>;
  if (!account) return <Navigate to="/login" replace />;
  // Employees who open an admin link land on their own dashboard instead.
  if (admin && account.role !== "admin") return <Navigate to="/me" replace />;
  return <>{children}</>;
}

function Home() {
  const { account, checking } = useAuth();
  if (checking) return <div className="loading">Checking your sign-in…</div>;
  if (!account) return <Navigate to="/login" replace />;
  return <Navigate to={account.role === "admin" ? "/admin" : "/me"} replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <TooltipProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireLogin><Shell /></RequireLogin>}>
              <Route
                path="/admin"
                element={
                  <RequireLogin admin>
                    <AdminPage />
                  </RequireLogin>
                }
              />
              <Route path="/me" element={<MePage />} />
            </Route>
            <Route path="*" element={<Home />} />
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </AuthProvider>
  </StrictMode>,
);
