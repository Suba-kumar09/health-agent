import { useEffect, useState } from "react";
import { DashboardApiError, fetchDashboardSummary } from "../api";
import type { DashboardSummary } from "../types";
import { formatDuration } from "../format";
import { StatTile } from "../components/StatTile";
import { ActivityTimeline } from "../components/ActivityTimeline";
import { GoalProgress } from "../components/GoalProgress";
import { MessageFeed } from "../components/MessageFeed";
import { AppUsageChart } from "../components/AppUsageChart";
import { ErrorNotice } from "../components/ErrorNotice";
import "./TodayPage.css";

function sumDuration(summary: DashboardSummary, state: "active" | "idle"): number {
  return summary.todaySegments
    .filter((s) => s.state === state)
    .reduce((total, s) => total + (s.endTs - s.startTs), 0);
}

export function TodayPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDashboardSummary()
      .then(setSummary)
      .catch((e: unknown) => setError(e instanceof DashboardApiError ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="today-page">
        <ErrorNotice message={error} />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="page-loading">
        <p>Loading your day…</p>
      </div>
    );
  }

  const activeSecs = sumDuration(summary, "active");
  const idleSecs = sumDuration(summary, "idle");

  const streakSecs = summary.currentStreak ? summary.now - summary.currentStreak.startedAt : 0;
  const streakStatus = streakSecs >= 90 * 60 ? "serious" : streakSecs >= 45 * 60 ? "warning" : undefined;

  return (
    <div className="today-page">
      <header className="today-page__header">
        <div>
          <h1 className="today-page__title">Your day</h1>
          <p className="today-page__subtitle">
            {summary.employeeName}
            {summary.deviceName ? <> &middot; {summary.deviceName}</> : " · no device enrolled yet"}
          </p>
        </div>
      </header>

      <div className="today-page__stats">
        <StatTile
          label="Current streak"
          value={summary.currentStreak ? formatDuration(streakSecs) : "—"}
          sublabel={summary.currentStreak ? "continuously active" : "currently idle"}
          status={streakStatus}
          statusLabel={
            streakStatus === "serious" ? "Take a break" : streakStatus === "warning" ? "Worth a break soon" : undefined
          }
        />
        <StatTile label="Active today" value={formatDuration(activeSecs)} sublabel="keyboard + mouse + focus" />
        <StatTile label="Idle today" value={formatDuration(idleSecs)} sublabel="breaks + away from desk" />
      </div>

      <div className="today-page__grid">
        <div className="today-page__main">
          <ActivityTimeline segments={summary.todaySegments} now={summary.now} />
          {summary.goal && <GoalProgress goal={summary.goal} now={summary.now} />}
        </div>
        <div className="today-page__side">
          <AppUsageChart appUsage={summary.appUsage} />
          <MessageFeed messages={summary.messages} now={summary.now} />
        </div>
      </div>
    </div>
  );
}
