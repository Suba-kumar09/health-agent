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
import { FlameIcon, KeyboardIcon, LockIcon, MoonIcon, SigmaIcon, SunIcon } from "../components/icons";
import type { ActivityState } from "../types";
import "./TodayPage.css";

function sumDuration(summary: DashboardSummary, state: ActivityState): number {
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
  const lockedSecs = sumDuration(summary, "locked");
  const totalSecs = activeSecs + idleSecs + lockedSecs;

  const streakSecs = summary.currentStreak ? summary.now - summary.currentStreak.startedAt : 0;
  const streakStatus = streakSecs >= 90 * 60 ? "serious" : streakSecs >= 45 * 60 ? "warning" : undefined;

  return (
    <div className="today-page">
      <header className="today-page__header">
        <span className="today-page__title-icon">
          <SunIcon size={26} />
        </span>
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
          label="Streak"
          value={summary.currentStreak ? formatDuration(streakSecs) : "—"}
          sublabel={summary.currentStreak ? "continuously active" : "currently idle"}
          status={streakStatus}
          statusLabel={
            streakStatus === "serious" ? "Take a break" : streakStatus === "warning" ? "Worth a break soon" : undefined
          }
          icon={<FlameIcon />}
          accent="var(--accent)"
        />
        <StatTile
          label="Active"
          value={formatDuration(activeSecs)}
          sublabel="keyboard + mouse + focus"
          icon={<KeyboardIcon />}
          accent="var(--series-1)"
        />
        <StatTile
          label="Idle"
          value={formatDuration(idleSecs)}
          sublabel="breaks + away from desk"
          icon={<MoonIcon />}
          accent="var(--series-4)"
        />
        <StatTile
          label="Locked"
          value={formatDuration(lockedSecs)}
          sublabel="workstation locked"
          icon={<LockIcon />}
          accent="var(--series-3)"
        />
        <StatTile
          label="Total"
          value={formatDuration(totalSecs)}
          sublabel="active + idle + locked"
          icon={<SigmaIcon />}
          accent="var(--series-2)"
        />
      </div>

      <div className="today-page__grid">
        <div className="today-page__main">
          <ActivityTimeline segments={summary.todaySegments} now={summary.now} />
          {summary.goal && <GoalProgress goal={summary.goal} now={summary.now} />}
        </div>
        <div className="today-page__side">
          <AppUsageChart appUsage={summary.appUsage} messages={summary.messages} now={summary.now} />
          <MessageFeed messages={summary.messages} now={summary.now} />
        </div>
      </div>
    </div>
  );
}
