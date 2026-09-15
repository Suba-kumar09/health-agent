import type { DashboardSummary } from "./types";

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
