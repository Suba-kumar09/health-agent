import { buildMockConsentSettings, buildMockGoalHistory, buildMockHistory, buildMockSummary } from "./mockData";
import type { ConsentSettings, DashboardSummary, DayHistoryEntry, GoalHistoryEntry } from "./types";

// No read endpoints exist on the backend yet (server/routes only has
// /goal, /v1/enroll, /v1/ingest, /v1/messages/pending — all write/ingest
// oriented). Once real GET endpoints are added server-side, swap the body
// of each function below for a fetch() call; the types already mirror the
// backend models so the pages shouldn't need to change.

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  return buildMockSummary();
}

export async function fetchHistory(): Promise<DayHistoryEntry[]> {
  return buildMockHistory();
}

export async function fetchGoalHistory(): Promise<GoalHistoryEntry[]> {
  return buildMockGoalHistory();
}

export async function fetchConsentSettings(): Promise<ConsentSettings> {
  return buildMockConsentSettings();
}

// Stand-in for the real POST /goal form (server/routes/goals.py) — that
// endpoint takes system_name/text/hours and returns an HTML page, not JSON,
// so this can't call it directly yet. Kept as a local-only append until a
// JSON-returning goal-creation endpoint exists.
export async function submitGoal(text: string, hours: number): Promise<GoalHistoryEntry> {
  const now = Math.floor(Date.now() / 1000);
  return {
    goalId: `local-${now}`,
    text,
    createdAt: now,
    deadlineAt: now + hours * 3600,
    metDeadline: null,
  };
}
