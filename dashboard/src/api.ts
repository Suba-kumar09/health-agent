import { API_BASE, SYSTEM_NAME } from "./config";
import type { ConsentSettings, DashboardSummary, DayHistoryEntry, GoalHistoryEntry, MessageKind } from "./types";
import { buildMockConsentSettings } from "./mockData";

export class DashboardApiError extends Error {}

function requireSystemName(): string {
  if (!SYSTEM_NAME) {
    throw new DashboardApiError(
      "VITE_SYSTEM_NAME is not set (see dashboard/.env.example) - the server has no auth system, " +
        "it looks up 'you' by this machine's hostname, same as the /goal form and agent enrollment.",
    );
  }
  return SYSTEM_NAME;
}

async function apiGet<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const url = new URL(path, API_BASE);
  url.searchParams.set("system_name", requireSystemName());
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));

  const res = await fetch(url);
  if (res.status === 404) {
    throw new DashboardApiError(
      `Server doesn't recognize system_name "${SYSTEM_NAME}" - register it first: ` +
        `python -m server.admin_cli add-employee --name "Your Name" --system-name ${SYSTEM_NAME}`,
    );
  }
  if (!res.ok) {
    throw new DashboardApiError(`${path} failed: HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

interface SummaryResponse {
  device_name: string | null;
  employee_name: string;
  now: number;
  today_segments: { state: "active" | "idle" | "locked"; start_ts: number; end_ts: number }[];
  current_streak: { state: "active" | "idle"; started_at: number } | null;
  goal: { text: string; created_at: number; deadline_at: number } | null;
  messages: { message_id: string; kind: string; text: string; created_at: number; label: string | null }[];
  app_usage: { app: string; secs: number }[];
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const r = await apiGet<SummaryResponse>("/v1/me/summary");
  return {
    deviceName: r.device_name,
    employeeName: r.employee_name,
    now: r.now,
    todaySegments: r.today_segments.map((s) => ({ state: s.state, startTs: s.start_ts, endTs: s.end_ts })),
    currentStreak: r.current_streak ? { state: r.current_streak.state, startedAt: r.current_streak.started_at } : null,
    goal: r.goal ? { text: r.goal.text, createdAt: r.goal.created_at, deadlineAt: r.goal.deadline_at } : null,
    // kind is a free-form str server-side (Message.kind); "break", "distraction",
    // and "idle" are the only values anything writes today (server/wellbeing.py,
    // server/goals.py, server/productivity.py).
    messages: r.messages.map((m) => ({
      messageId: m.message_id,
      kind: m.kind as MessageKind,
      text: m.text,
      createdAt: m.created_at,
      label: m.label,
    })),
    appUsage: r.app_usage.map((a) => ({ app: a.app, secs: a.secs })),
  };
}

interface HistoryEntryResponse {
  date: string;
  active_secs: number;
  idle_secs: number;
  locked_secs: number;
  distraction_secs: number;
  top_app: string | null;
}

export async function fetchHistory(): Promise<DayHistoryEntry[]> {
  const r = await apiGet<HistoryEntryResponse[]>("/v1/me/history", { days: 14 });
  return r.map((e) => ({
    date: e.date,
    activeSecs: e.active_secs,
    idleSecs: e.idle_secs,
    lockedSecs: e.locked_secs,
    distractionSecs: e.distraction_secs,
    topApp: e.top_app,
  }));
}

interface GoalEntryResponse {
  goal_id: string;
  text: string;
  created_at: number;
  deadline_at: number;
}

export async function fetchGoalHistory(): Promise<GoalHistoryEntry[]> {
  const r = await apiGet<GoalEntryResponse[]>("/v1/me/goals");
  return r.map((g) => ({ goalId: g.goal_id, text: g.text, createdAt: g.created_at, deadlineAt: g.deadline_at }));
}

// No server-side record of consent/capture-mode/collectors - that's agent-local
// state (config.toml, consent.json), not something the ingest server tracks.
// Left on mock data until/unless a local read route is added to
// agent/collectors/browser_bridge.py.
export async function fetchConsentSettings(): Promise<ConsentSettings> {
  return buildMockConsentSettings();
}

// Reuses the real POST /goal form (server/routes/goals.py) - it's an
// HTML-form endpoint, not JSON, so success is "got a 2xx back"; the goal
// list is then re-fetched from GET /v1/me/goals rather than parsed out of
// the HTML response.
export async function submitGoal(text: string, hours: number): Promise<GoalHistoryEntry[]> {
  const systemName = requireSystemName();
  const body = new URLSearchParams({ system_name: systemName, text, hours: String(hours) });
  const res = await fetch(new URL("/goal", API_BASE), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    throw new DashboardApiError(`Setting the goal failed: HTTP ${res.status}`);
  }
  return fetchGoalHistory();
}
