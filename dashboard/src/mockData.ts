import type { ConsentSettings, DashboardSummary, DayHistoryEntry, GoalHistoryEntry } from "./types";

// Stand-in for a real GET /v1/me/summary response. Anchored to "now" (rather
// than fixed clock times) so the demo looks sane no matter when it's viewed.
// Replace with a real fetch in api.ts once that endpoint exists server-side.
export function buildMockSummary(): DashboardSummary {
  const now = Math.floor(Date.now() / 1000);

  const streakStart = now - 47 * 60;
  const lunchEnd = streakStart;
  const lunchStart = lunchEnd - 42 * 60;
  const morningActiveEnd = lunchStart;
  const morningActiveStart = morningActiveEnd - 130 * 60;
  const breakEnd = morningActiveStart;
  const breakStart = breakEnd - 11 * 60;
  const dayStart = breakStart - 95 * 60;

  return {
    deviceName: "DESKTOP-BHARATH",
    employeeName: "Bharath",
    now,
    todaySegments: [
      { state: "active", startTs: dayStart, endTs: breakStart },
      { state: "idle", startTs: breakStart, endTs: breakEnd },
      { state: "active", startTs: morningActiveStart, endTs: morningActiveEnd },
      { state: "idle", startTs: lunchStart, endTs: lunchEnd },
      { state: "active", startTs: streakStart, endTs: now },
    ],
    currentStreak: { state: "active", startedAt: streakStart },
    goal: {
      text: "Finish the quarterly report",
      createdAt: dayStart,
      deadlineAt: now + 95 * 60,
    },
    messages: [
      {
        messageId: "m2",
        kind: "break",
        createdAt: now - 130 * 60,
        text: "You've been continuously active for 90 minutes — take a short break now, your body needs the rest.",
      },
      {
        messageId: "m1",
        kind: "distraction",
        createdAt: now - 205 * 60,
        text: "You've been on YouTube for 12 minutes instead of the quarterly report, due in 3 hours — close the tab and get back to it.",
      },
    ],
  };
}

const TOP_APPS = ["VS Code", "Chrome", "Slack", "Figma", "Terminal", "Notion", "Chrome"];

export function buildMockHistory(days = 14): DayHistoryEntry[] {
  const entries: DayHistoryEntry[] = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const isWeekend = d.getDay() === 0 || d.getDay() === 6;
    const activeHours = isWeekend ? 0.5 + Math.random() * 1.5 : 4 + Math.random() * 3.5;
    const idleHours = isWeekend ? 0.2 + Math.random() * 0.5 : 0.6 + Math.random() * 1.2;
    entries.push({
      date: d.toISOString().slice(0, 10),
      activeSecs: Math.round(activeHours * 3600),
      idleSecs: Math.round(idleHours * 3600),
      topApp: TOP_APPS[i % TOP_APPS.length],
    });
  }
  return entries;
}

export function buildMockGoalHistory(): GoalHistoryEntry[] {
  const now = Math.floor(Date.now() / 1000);
  const day = 24 * 60 * 60;
  return [
    {
      goalId: "g5",
      text: "Finish the quarterly report",
      createdAt: now - 95 * 60,
      deadlineAt: now + 95 * 60,
      metDeadline: null,
    },
    {
      goalId: "g4",
      text: "Review PR #482 and reply to the design thread",
      createdAt: now - day - 6 * 3600,
      deadlineAt: now - day - 2 * 3600,
      metDeadline: true,
    },
    {
      goalId: "g3",
      text: "Draft the onboarding doc for new hires",
      createdAt: now - 2 * day - 5 * 3600,
      deadlineAt: now - 2 * day - 1 * 3600,
      metDeadline: false,
    },
    {
      goalId: "g2",
      text: "Fix the flaky uploader retry test",
      createdAt: now - 3 * day - 7 * 3600,
      deadlineAt: now - 3 * day - 3 * 3600,
      metDeadline: true,
    },
    {
      goalId: "g1",
      text: "Prep slides for the Friday sync",
      createdAt: now - 4 * day - 6 * 3600,
      deadlineAt: now - 4 * day - 2 * 3600,
      metDeadline: true,
    },
  ];
}

export function buildMockConsentSettings(): ConsentSettings {
  return {
    basicConsentedAt: Math.floor(Date.now() / 1000) - 21 * 24 * 3600,
    detailedConsentedAt: null,
    captureMode: "aggregate",
    encryptAtRest: true,
    collectors: [
      { name: "input_watcher", label: "Keyboard & mouse activity (counts only)", enabled: true },
      { name: "window_watcher", label: "Active app / window title", enabled: true },
      { name: "afk", label: "Away-from-keyboard detection", enabled: true },
      { name: "browser_bridge", label: "Active browser tab (via extension)", enabled: true },
    ],
  };
}
