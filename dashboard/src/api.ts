import type { Account, Day, EmployeeDetail, Goal, Overview, Today } from "./types";

// Empty by default: requests go to the same origin and Vite's dev proxy
// forwards /v1 to the server (see vite.config.ts). Set VITE_API_BASE only
// when the dashboard is served from somewhere that can't proxy.
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const TOKEN_KEY = "ha-dashboard-token";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage blocked (private window): the session just won't survive a reload.
  }
}

// Fired when the server says the session is gone, so the app returns to login.
export const SESSION_EXPIRED = "ha-session-expired";

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that it's running on port 8001.", 0);
  }
  if (res.status === 401 && path !== "/v1/auth/login") {
    setToken(null);
    window.dispatchEvent(new Event(SESSION_EXPIRED));
  }
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status}).`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // Not JSON; keep the generic message.
    }
    throw new ApiError(detail, res.status);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export async function login(loginName: string, password: string): Promise<Account> {
  const data = await request<{ token: string; account: Account }>("POST", "/v1/auth/login", {
    login: loginName,
    password,
  });
  setToken(data.token);
  return data.account;
}

export async function logout(): Promise<void> {
  try {
    await request("POST", "/v1/auth/logout");
  } finally {
    setToken(null);
  }
}

export const fetchAccount = () => request<Account>("GET", "/v1/auth/me");
export const fetchToday = () => request<Today>("GET", "/v1/me/today");
export const fetchWeek = () => request<Day[]>("GET", "/v1/me/week");
export const setGoal = (text: string, hours: number) => request<Goal>("POST", "/v1/me/goal", { text, hours });
export const fetchOverview = () => request<Overview>("GET", "/v1/admin/overview");
export const fetchEmployee = (id: string) =>
  request<EmployeeDetail>("GET", `/v1/admin/employees/${encodeURIComponent(id)}`);
