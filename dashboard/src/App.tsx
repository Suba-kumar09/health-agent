import { useEffect, useState } from "react";
import { fetchDashboardSummary } from "./api";
import type { DashboardSummary } from "./types";
import { formatDuration } from "./format";
import { StatTile } from "./components/StatTile";
import { ActivityTimeline } from "./components/ActivityTimeline";
import { GoalProgress } from "./components/GoalProgress";
import { MessageFeed } from "./components/MessageFeed";
import "./App.css";

function sumDuration(summary: DashboardSummary, state: "active" | "idle"): number {
  return summary.todaySegments
    .filter((s) => s.state === state)
    .reduce((total, s) => total + (s.endTs - s.startTs), 0);
}

function App() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);

  useEffect(() => {
    fetchDashboardSummary().then(setSummary);
  }, []);

  if (!summary) {
    return (
      <div className="app-loading">
        <p>Loading your day…</p>
      </div>
    );
  }

  const activeSecs = sumDuration(summary, "active");
  const idleSecs = sumDuration(summary, "idle");

  const streakSecs = summary.currentStreak ? summary.now - summary.currentStreak.startedAt : 0;
  const streakStatus = streakSecs >= 90 * 60 ? "serious" : streakSecs >= 45 * 60 ? "warning" : undefined;

  return (
    <div className="app">
      <header className="app__header">
        <div>
          <h1 className="app__title">Your day</h1>
          <p className="app__subtitle">
            {summary.employeeName} &middot; {summary.deviceName}
          </p>
        </div>
      </header>

      <div className="app__stats">
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

      <div className="app__grid">
        <div className="app__main">
          <ActivityTimeline segments={summary.todaySegments} now={summary.now} />
          {summary.goal && <GoalProgress goal={summary.goal} now={summary.now} />}
        </div>
        <div className="app__side">
          <MessageFeed messages={summary.messages} now={summary.now} />
        </div>
      </div>
    </div>
  );
}

export default App;
