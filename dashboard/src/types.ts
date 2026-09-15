// Shapes intentionally mirror the backend's real models so wiring this up to
// a live endpoint later (see api.ts) is a data-source swap, not a rewrite.
// See server/models.py (Event, Goal, Message) and server/wellbeing.py /
// server/goals.py (streak + nudge logic) on the `openai-agents` branch.

export type ActivityState = "active" | "idle";

export interface ActivitySegment {
  state: ActivityState;
  startTs: number; // unix seconds
  endTs: number; // unix seconds
}

export interface GoalSummary {
  text: string;
  createdAt: number; // unix seconds
  deadlineAt: number; // unix seconds
}

export type MessageKind = "break" | "distraction";

export interface NudgeMessage {
  messageId: string;
  kind: MessageKind;
  text: string;
  createdAt: number; // unix seconds
}

export interface DashboardSummary {
  deviceName: string | null; // null if the employee is registered but no device has enrolled yet
  employeeName: string;
  now: number; // unix seconds, server/mock clock
  todaySegments: ActivitySegment[];
  currentStreak: {
    state: ActivityState;
    startedAt: number;
  } | null;
  goal: GoalSummary | null;
  messages: NudgeMessage[];
}

export interface DayHistoryEntry {
  date: string; // YYYY-MM-DD
  activeSecs: number;
  idleSecs: number;
  topApp: string | null;
}

// No "completed" flag exists server-side (see server/models.py's Goal
// docstring - deliberate MVP scope), so a past goal can only be shown as
// "in progress" or "overdue", never "met"/"missed" - the data to say which
// doesn't exist.
export interface GoalHistoryEntry {
  goalId: string;
  text: string;
  createdAt: number;
  deadlineAt: number;
}

// Mirrors agent/consent.py's separate basic/detailed flags and config.toml's
// [collectors]/[privacy] tables - read-only here, this dashboard doesn't
// change device-side settings.
export interface ConsentSettings {
  basicConsentedAt: number | null;
  detailedConsentedAt: number | null;
  captureMode: "aggregate" | "detailed";
  encryptAtRest: boolean;
  collectors: { name: string; label: string; enabled: boolean }[];
}
