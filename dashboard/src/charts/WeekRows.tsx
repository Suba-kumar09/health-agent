import { duration, hoursLabel, isWeekend, weekday } from "../format";
import type { Day } from "../types";
import { LegendDot } from "../ui/bits";
import { useTooltip } from "../ui/Tooltip";

const PARTS = ["active", "idle", "distraction"] as const;

export function focusShare(day: Day): number | null {
  const tracked = day.totals.active + day.totals.idle + day.totals.distraction;
  return tracked > 0 ? Math.round((day.totals.active / tracked) * 100) : null;
}

// One row per day: a stacked bar, the total, and the focus share (active time
// out of active + idle + distraction). Bars share one scale that always
// includes the workday, and a thin mark shows where the workday ends.
export function WeekRows({
  days,
  workdaySecs,
  onOpen,
}: {
  days: Day[];
  workdaySecs: number;
  onOpen: (day: Day) => void;
}) {
  const { tipProps } = useTooltip();
  const tracked = (d: Day) => d.totals.active + d.totals.idle + d.totals.distraction;
  const max = Math.max(...days.map(tracked), workdaySecs, 1);
  const workdayPct = (workdaySecs / max) * 100;
  const todayDate = days.length ? days[days.length - 1].date : "";

  return (
    <>
      <div className="week">
        {days.map((d) => {
          const total = tracked(d);
          const focus = focusShare(d);
          const isToday = d.date === todayDate;
          const label = (
            <span className="week-day">
              {weekday(d.date)}
              {isToday && <small>Today</small>}
              {!isToday && isWeekend(d.date) && <small className="we">Weekend</small>}
            </span>
          );
          if (total <= 0) {
            return (
              <div className={`week-row empty${isToday ? " today" : ""}`} key={d.date}>
                {label}
                <span className="hint">No activity</span>
                <span />
                <span />
              </div>
            );
          }
          return (
            <button
              className={`week-row${isToday ? " today" : ""}`}
              key={d.date}
              onClick={() => onOpen(d)}
              {...tipProps(
                <>
                  <b>{weekday(d.date)}</b> · {duration(total)} of {hoursLabel(workdaySecs)}
                  <br />
                  Active {duration(d.totals.active)} · Idle {duration(d.totals.idle)} · Distraction{" "}
                  {duration(d.totals.distraction)}
                  <em>Click for details</em>
                </>,
              )}
            >
              {label}
              <span className="week-track">
                <span className="week-target" style={{ left: `${workdayPct}%` }} aria-hidden="true" />
                <span className="week-bar" style={{ width: `${(total / max) * 100}%` }}>
                  {PARTS.filter((k) => d.totals[k] > 0).map((k) => (
                    <span key={k} className={`s dot-${k}`} style={{ flex: d.totals[k] }} />
                  ))}
                </span>
              </span>
              <span className="week-total">{(total / 3600).toFixed(1)}h</span>
              <span className={`focus${focus != null && focus >= 80 ? " hi" : ""}`}>{focus}% focus</span>
            </button>
          );
        })}
      </div>
      <div className="legend-inline" style={{ marginTop: 12, paddingLeft: 8 }}>
        <span className="legend-row">
          <span className="week-target-key" aria-hidden="true" />
          <span className="lbl">{hoursLabel(workdaySecs)} workday</span>
        </span>
        {PARTS.map((k) => (
          <span className="legend-row" key={k}>
            <LegendDot state={k} />
            <span className="lbl">{k === "active" ? "Active" : k === "idle" ? "Idle" : "Distraction"}</span>
          </span>
        ))}
      </div>
    </>
  );
}
