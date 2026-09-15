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
  deviceName: string;
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
