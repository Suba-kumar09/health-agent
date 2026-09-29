import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import * as api from "./api";
import type { Account } from "./types";

interface AuthState {
  account: Account | null;
  checking: boolean; // true while an existing session is being verified on load
  signIn: (login: string, password: string) => Promise<Account>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [checking, setChecking] = useState(() => api.getToken() != null);

  useEffect(() => {
    if (!api.getToken()) return;
    api
      .fetchAccount()
      .then(setAccount)
      .catch(() => setAccount(null))
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    const expired = () => setAccount(null);
    window.addEventListener(api.SESSION_EXPIRED, expired);
    return () => window.removeEventListener(api.SESSION_EXPIRED, expired);
  }, []);

  const signIn = useCallback(async (login: string, password: string) => {
    const acc = await api.login(login, password);
    setAccount(acc);
    return acc;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setAccount(null);
    }
  }, []);

  return <AuthContext.Provider value={{ account, checking, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
