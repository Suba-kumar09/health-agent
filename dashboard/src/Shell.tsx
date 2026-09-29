import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { initials } from "./format";
import { LiveContext, useNow, type LiveState } from "./hooks";
import { LogoutIcon, MoonIcon, PulseMark, SunIcon } from "./ui/icons";

const ORG_NAME = import.meta.env.VITE_ORG_NAME?.trim();
const THEME_KEY = "ha-theme";

function readTheme(): "light" | "dark" | null {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : null;
  } catch {
    return null;
  }
}

function effectiveTheme(choice: "light" | "dark" | null): "light" | "dark" {
  if (choice) return choice;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <PulseMark />
      </span>
      <span className="brand-text">
        <strong>Health Agent</strong>
        <span>{ORG_NAME ? `${ORG_NAME} · Wellbeing Console` : "Wellbeing Console"}</span>
      </span>
    </div>
  );
}

export function Shell() {
  const { account, signOut } = useAuth();
  const navigate = useNavigate();
  const now = useNow(1000);
  const [live, setLive] = useState<LiveState>({ updatedAt: null, failing: false });
  const report = useCallback((s: LiveState) => {
    setLive((prev) => (s.failing ? { ...prev, failing: true } : s));
  }, []);
  const [theme, setTheme] = useState(readTheme);

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }, [theme]);

  const toggleTheme = () => {
    const next = effectiveTheme(theme) === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // Not persisted; still applies for this visit.
    }
  };

  const onSignOut = async () => {
    await signOut();
    navigate("/login");
  };

  if (!account) return null;
  const age = live.updatedAt == null ? null : Math.max(0, Math.round(now - live.updatedAt / 1000));
  const stale = live.failing || age == null || age > 90;

  return (
    <LiveContext.Provider value={report}>
      <div className="app">
        <header className="topbar">
          <Brand />
          {account.role === "admin" && (
            <nav className="seg" aria-label="Dashboard view">
              <NavLink to="/admin" className={({ isActive }) => (isActive ? "on" : "")}>
                Admin overview
              </NavLink>
              <NavLink to="/me" className={({ isActive }) => (isActive ? "on" : "")}>
                My dashboard
              </NavLink>
            </nav>
          )}
          <div className={`live${stale ? " stale" : ""}`} aria-live="polite">
            <span className="dot" aria-hidden="true" />
            <span>
              {live.failing
                ? "Can't reach the server"
                : age == null
                  ? "Loading…"
                  : `Live · updated ${age < 60 ? `${age}s` : `${Math.round(age / 60)}m`} ago`}
            </span>
          </div>
          <button
            className="icon-btn"
            onClick={toggleTheme}
            aria-label={effectiveTheme(theme) === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {effectiveTheme(theme) === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
          <div className="who">
            <span className="avatar">{initials(account.name)}</span>
            <span className="who-text">
              <strong>{account.name}</strong>
              <span>{account.role === "admin" ? "Admin" : "Employee"}</span>
            </span>
            <button className="icon-btn" onClick={onSignOut} aria-label="Sign out" title="Sign out">
              <LogoutIcon />
            </button>
          </div>
        </header>
        <Outlet />
      </div>
    </LiveContext.Provider>
  );
}
