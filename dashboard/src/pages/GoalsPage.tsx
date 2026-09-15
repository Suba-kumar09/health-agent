import { useEffect, useState, type FormEvent } from "react";
import { DashboardApiError, fetchGoalHistory, submitGoal } from "../api";
import type { GoalHistoryEntry } from "../types";
import { formatClock, formatDuration } from "../format";
import { ErrorNotice } from "../components/ErrorNotice";
import "./GoalsPage.css";

// No "completed" flag exists server-side (see types.ts) - a goal can only be
// shown as in-progress or overdue, never met/missed.
function statusFor(goal: GoalHistoryEntry, now: number): { label: string; className: string } {
  return goal.deadlineAt < now
    ? { label: "Overdue", className: "critical" }
    : { label: "In progress", className: "neutral" };
}

export function GoalsPage() {
  const [goals, setGoals] = useState<GoalHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [hours, setHours] = useState("2");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchGoalHistory()
      .then(setGoals)
      .catch((e: unknown) => setError(e instanceof DashboardApiError ? e.message : String(e)));
  }, []);

  const now = Math.floor(Date.now() / 1000);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const hoursNum = parseFloat(hours);
    if (!text.trim() || !hoursNum || hoursNum <= 0) return;
    setSubmitting(true);
    try {
      const updated = await submitGoal(text.trim(), hoursNum);
      setGoals(updated);
      setText("");
      setHours("2");
    } catch (err) {
      setError(err instanceof DashboardApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="goals-page">
      <header className="goals-page__header">
        <h1 className="goals-page__title">Goals</h1>
        <p className="goals-page__subtitle">
          Posts to the real <code>/goal</code> form on the agent server — set what you're working on and by when.
        </p>
      </header>

      <form className="goal-form" onSubmit={handleSubmit}>
        <div className="goal-form__field">
          <label htmlFor="goal-text">Goal</label>
          <input
            id="goal-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Finish the quarterly report"
            required
          />
        </div>
        <div className="goal-form__field goal-form__field--hours">
          <label htmlFor="goal-hours">Hours</label>
          <input
            id="goal-hours"
            type="number"
            min="0.5"
            step="0.5"
            value={hours}
            onChange={(e) => setHours(e.target.value)}
            required
          />
        </div>
        <button type="submit" disabled={submitting}>
          Set goal
        </button>
      </form>

      {error && <ErrorNotice message={error} />}

      {!goals ? (
        !error && (
          <div className="page-loading">
            <p>Loading goals…</p>
          </div>
        )
      ) : (
        <ul className="goal-list">
          {goals.map((g) => {
            const status = statusFor(g, now);
            return (
              <li key={g.goalId} className="goal-list__item">
                <div className="goal-list__main">
                  <p className="goal-list__text">{g.text}</p>
                  <p className="goal-list__meta">
                    Set {formatClock(g.createdAt)} &middot; due in {formatDuration(g.deadlineAt - g.createdAt)}
                  </p>
                </div>
                <span className={`goal-list__status goal-list__status--${status.className}`}>
                  <span className="goal-list__status-dot" aria-hidden="true" />
                  {status.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
