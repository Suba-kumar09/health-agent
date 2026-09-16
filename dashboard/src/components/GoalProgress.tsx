import type { GoalSummary } from "../types";
import { formatDuration } from "../format";
import { TargetIcon } from "./icons";
import "./GoalProgress.css";

interface GoalProgressProps {
  goal: GoalSummary;
  now: number;
}

export function GoalProgress({ goal, now }: GoalProgressProps) {
  const total = Math.max(1, goal.deadlineAt - goal.createdAt);
  const elapsed = Math.min(total, Math.max(0, now - goal.createdAt));
  const fraction = elapsed / total;
  const remaining = goal.deadlineAt - now;

  let status: "warning" | "serious" | "critical" | null = null;
  if (remaining <= 0) status = "critical";
  else if (fraction >= 0.8) status = "serious";
  else if (fraction >= 0.6) status = "warning";

  return (
    <div className="goal-progress">
      <div className="goal-progress__header">
        <h2 className="goal-progress__title">
          <TargetIcon size={15} />
          Today's goal
        </h2>
        {status && (
          <span className={`goal-progress__badge goal-progress__badge--${status}`}>
            <span className="goal-progress__badge-dot" aria-hidden="true" />
            {status === "critical" ? "Overdue" : "Due soon"}
          </span>
        )}
      </div>
      <p className="goal-progress__text">{goal.text}</p>
      <div className="goal-progress__bar">
        <div
          className={`goal-progress__fill${status ? ` goal-progress__fill--${status}` : ""}`}
          style={{ width: `${Math.round(fraction * 100)}%` }}
        />
      </div>
      <div className="goal-progress__footer">
        {remaining > 0 ? (
          <span>{formatDuration(remaining)} remaining</span>
        ) : (
          <span>Deadline passed {formatDuration(-remaining)} ago</span>
        )}
      </div>
    </div>
  );
}
