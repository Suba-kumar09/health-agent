import { useEffect, useState } from "react";
import { DashboardApiError, fetchHistory } from "../api";
import type { DayHistoryEntry } from "../types";
import { formatDuration } from "../format";
import { DailyActivityChart } from "../components/DailyActivityChart";
import { ErrorNotice } from "../components/ErrorNotice";
import "./HistoryPage.css";

function fullDateLabel(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function HistoryPage() {
  const [entries, setEntries] = useState<DayHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHistory()
      .then(setEntries)
      .catch((e: unknown) => setError(e instanceof DashboardApiError ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="history-page">
        <ErrorNotice message={error} />
      </div>
    );
  }

  if (!entries) {
    return (
      <div className="page-loading">
        <p>Loading history…</p>
      </div>
    );
  }

  const reversed = [...entries].reverse();

  return (
    <div className="history-page">
      <header className="history-page__header">
        <h1 className="history-page__title">History</h1>
        <p className="history-page__subtitle">Your activity over the last two weeks</p>
      </header>

      <DailyActivityChart entries={entries} />

      <div className="history-table">
        <div className="history-table__row history-table__row--head">
          <span>Date</span>
          <span>Active</span>
          <span>Idle</span>
          <span>Distraction</span>
          <span>Top app</span>
        </div>
        {reversed.map((e) => (
          <div key={e.date} className="history-table__row">
            <span>{fullDateLabel(e.date)}</span>
            <span>{formatDuration(e.activeSecs)}</span>
            <span>{formatDuration(e.idleSecs)}</span>
            <span className={e.distractionSecs > 0 ? "history-table__distraction" : undefined}>
              {e.distractionSecs > 0 ? formatDuration(e.distractionSecs) : "—"}
            </span>
            <span>{e.topApp ?? "—"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
