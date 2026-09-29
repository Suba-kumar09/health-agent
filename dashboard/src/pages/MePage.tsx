import { useCallback, useState, type FormEvent } from "react";
import * as api from "../api";
import { DayTimeline } from "../charts/DayTimeline";
import { focusShare, WeekRows } from "../charts/WeekRows";
import { ago, clock, duration, hoursLabel, KIND_LABEL, STATE_LABEL, STATUS_LABEL, weekday } from "../format";
import { useNow, usePolling } from "../hooks";
import type { AppUsage, Day, Message, Segment, Today } from "../types";
import {
  Chip,
  HBars,
  KIND_ICON,
  Kpi,
  MessageFeed,
  SectionTitle,
  StatusChip,
  TotalsTiles,
  WindowList,
} from "../ui/bits";
import { Drawer } from "../ui/Drawer";
import { ClockIcon, PointerIcon } from "../ui/icons";

type Detail =
  | { type: "segment"; seg: Segment }
  | { type: "day"; day: Day }
  | { type: "app"; app: AppUsage }
  | { type: "message"; msg: Message };

export function MePage() {
  const today = usePolling(api.fetchToday, 20_000);
  const week = usePolling(api.fetchWeek, 120_000);
  const now = useNow(30_000);
  const [detail, setDetail] = useState<Detail | null>(null);
  const close = useCallback(() => setDetail(null), []);

  const t = today.data;
  if (!t) {
    return today.error ? <div className="banner">{today.error}</div> : <div className="loading">Loading your day…</div>;
  }
  const serverNow = Math.max(t.now, now);
  const selectedSegment = detail?.type === "segment" ? detail.seg.start_ts : null;

  return (
    <>
      {today.error && <div className="banner">Couldn't refresh: {today.error} Showing the last data loaded.</div>}
      {t.status.status === "no_device" && (
        <div className="banner info">
          No computer is linked to your account yet. Once the Health Agent runs on your machine, your day shows up
          here.
        </div>
      )}

      <MyKpis today={t} week={week.data} now={serverNow} />

      <div className="section-head">
        <h2>Today</h2>
        <span className="hint">
          {new Date(t.day_start * 1000).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" })}
        </span>
      </div>
      <div className="card">
        {t.segments.length === 0 ? (
          <div className="empty">No activity recorded yet today.</div>
        ) : (
          <>
            <DayTimeline
              segments={t.segments}
              dayStart={t.day_start}
              now={serverNow}
              workdaySecs={t.workday_secs}
              selected={selectedSegment}
              onOpen={(seg) => setDetail({ type: "segment", seg })}
            />
            <div className="click-hint">
              <PointerIcon />
              Click any color on the line to see which windows and tabs were open
            </div>
          </>
        )}
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head">
            <h3>This week</h3>
            <span className="sub">hours per day · focus = active share</span>
          </div>
          {week.data ? (
            <WeekRows
              days={week.data}
              workdaySecs={t.workday_secs}
              onOpen={(day) => setDetail({ type: "day", day })}
            />
          ) : (
            <div className="empty">{week.error ?? "Loading…"}</div>
          )}
        </div>
        <div className="card">
          <GoalCard today={t} now={serverNow} onSaved={today.reload} />
          <div className="card-head" style={{ marginTop: 22 }}>
            <h3>Apps today</h3>
            <span className="sub">click to see titles</span>
          </div>
          <HBars
            empty="No apps used yet today."
            rows={t.apps.map((a) => ({
              key: a.app,
              name: a.app,
              secs: a.secs,
              tip: (
                <>
                  <b>{a.app}</b> · {duration(a.secs)}
                  {a.windows[0] && <em>Top: {a.windows[0].title ?? a.windows[0].app}</em>}
                </>
              ),
            }))}
            onOpen={(key) => {
              const app = t.apps.find((a) => a.app === key);
              if (app) setDetail({ type: "app", app });
            }}
          />
        </div>
      </div>

      <div className="section-head">
        <h2>My notifications</h2>
      </div>
      <div className="card">
        <MessageFeed
          messages={t.messages}
          now={serverNow}
          showWho={false}
          empty="No reminders yet."
          onOpen={(msg) => setDetail({ type: "message", msg })}
        />
      </div>

      {detail && <MyDetail detail={detail} today={t} now={serverNow} onClose={close} />}
    </>
  );
}

function MyKpis({ today, week, now }: { today: Today; week: Day[] | null; now: number }) {
  const s = today.status;
  const worked = (week ?? []).filter((d) => d.totals.active > 0);
  const avg = worked.length ? worked.reduce((sum, d) => sum + d.totals.active, 0) / worked.length : null;
  const goal = today.goal;
  const goalLeft = goal ? goal.deadline_at - now : null;
  return (
    <div className="kpi-row">
      <Kpi
        label="Active today"
        value={duration(today.totals.active)}
        sub={`of ${hoursLabel(today.workday_secs)} workday${today.totals.distraction >= 60 ? ` · ${duration(today.totals.distraction)} distracted` : ""}`}
        chip={<StatusChip status="active" text="Today" />}
      />
      <Kpi
        label="Right now"
        value={s.since != null && s.status !== "offline" && s.status !== "no_device" ? duration(now - s.since) : "—"}
        sub={
          s.status === "offline"
            ? `last seen ${ago(s.last_seen_at, now)}`
            : s.status === "no_device"
              ? "no computer linked"
              : `${STATUS_LABEL[s.status].toLowerCase()} streak`
        }
        chip={<StatusChip status={s.status} />}
      />
      <Kpi
        label="Daily average"
        value={avg == null ? "—" : `${(avg / 3600).toFixed(1)}h`}
        sub={worked.length ? `active, over ${worked.length} day${worked.length === 1 ? "" : "s"} this week` : "no activity this week"}
        chip={<Chip tone="neutral" icon={<ClockIcon />}>This week</Chip>}
      />
      <Kpi
        label="Goal deadline"
        value={goalLeft == null ? "—" : goalLeft > 0 ? duration(goalLeft) : "Past due"}
        sub={goal ? goal.text : "no goal set"}
        chip={
          goal ? (
            <StatusChip status={goalLeft != null && goalLeft < 3 * 3600 ? "idle" : "active"} text={goalLeft != null && goalLeft < 3 * 3600 ? "Due soon" : "On track"} />
          ) : (
            <Chip tone="neutral">None</Chip>
          )
        }
      />
    </div>
  );
}

const HOUR_OPTIONS = [1, 2, 3, 4, 6, 8, 24, 48, 72];

function GoalCard({ today, now, onSaved }: { today: Today; now: number; onSaved: () => void }) {
  const goal = today.goal;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [hours, setHours] = useState(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.setGoal(text.trim(), hours);
      setEditing(false);
      setText("");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the goal.");
    } finally {
      setBusy(false);
    }
  };

  const progress = goal
    ? Math.min(100, Math.max(0, ((now - goal.created_at) / (goal.deadline_at - goal.created_at)) * 100))
    : 0;

  return (
    <>
      <div className="card-head">
        <h3>Goal</h3>
        {!editing && (
          <button className="linkish" onClick={() => setEditing(true)}>
            {goal ? "Set a new goal" : "Set a goal"}
          </button>
        )}
      </div>
      {goal ? (
        <>
          <div className="goal-text">{goal.text}</div>
          <div className="meter-track">
            <div className="meter-fill" style={{ width: `${progress}%` }} />
          </div>
          <div className="meter-labels">
            <span>Set {ago(goal.created_at, now)}</span>
            <span className="mono">Due {clock(goal.deadline_at)}</span>
          </div>
        </>
      ) : (
        !editing && <div className="empty">No goal right now. A goal lets distraction reminders mention it.</div>
      )}
      {editing && (
        <form className="goal-form" onSubmit={submit}>
          <input
            id="goal-text"
            aria-label="Goal"
            placeholder="e.g. Finish the Q3 report"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={300}
            required
            autoFocus
          />
          <select id="goal-hours" aria-label="Time to finish" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {HOUR_OPTIONS.map((h) => (
              <option key={h} value={h}>
                {h < 24 ? `in ${h}h` : `in ${h / 24} day${h === 24 ? "" : "s"}`}
              </option>
            ))}
          </select>
          <button className="btn primary" type="submit" disabled={busy || !text.trim()}>
            {busy ? "Saving…" : "Save goal"}
          </button>
          <button className="btn" type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
          {error && <div className="hint" style={{ color: "var(--critical)", width: "100%" }}>{error}</div>}
        </form>
      )}
    </>
  );
}

function MyDetail({ detail, today, now, onClose }: { detail: Detail; today: Today; now: number; onClose: () => void }) {
  if (detail.type === "segment") {
    const s = detail.seg;
    const notes: Partial<Record<Segment["state"], string>> = {
      idle: "No keyboard or mouse input. These windows were on screen while you were away.",
      locked: "Your computer was locked, so nothing was captured.",
    };
    return (
      <Drawer
        chip={<StatusChip status={s.state} text={STATE_LABEL[s.state]} />}
        title={`${clock(s.start_ts)} – ${clock(s.end_ts)}`}
        meta={`${duration(s.end_ts - s.start_ts)} ${STATE_LABEL[s.state].toLowerCase()}`}
        onClose={onClose}
      >
        {notes[s.state] && <div className="note">{notes[s.state]}</div>}
        {s.state !== "locked" && (
          <>
            <SectionTitle>{s.state === "idle" ? "On screen while idle" : "What was on screen"}</SectionTitle>
            <WindowList items={s.windows} empty="No window was captured for this stretch." />
          </>
        )}
      </Drawer>
    );
  }

  if (detail.type === "day") {
    const d = detail.day;
    const focus = focusShare(d);
    return (
      <Drawer
        chip={<Chip tone="accent" icon={<ClockIcon />}>{weekday(d.date)}</Chip>}
        title={new Date(`${d.date}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}
        meta={focus == null ? undefined : `Focus ${focus}% · active share of tracked time`}
        onClose={onClose}
      >
        <TotalsTiles totals={d.totals} target={today.workday_secs} />
        <SectionTitle>Most used</SectionTitle>
        <WindowList items={d.top_windows} empty="Nothing captured." />
        <SectionTitle>Flagged as distraction</SectionTitle>
        <WindowList items={d.flagged_windows} empty="Nothing flagged. Nice." />
      </Drawer>
    );
  }

  if (detail.type === "app") {
    const a = detail.app;
    return (
      <Drawer
        chip={<Chip tone="neutral">Today</Chip>}
        title={a.app}
        meta={`${duration(a.secs)} across ${a.windows.length} window${a.windows.length === 1 ? "" : "s"}`}
        onClose={onClose}
      >
        <SectionTitle>Titles</SectionTitle>
        <WindowList items={a.windows} />
      </Drawer>
    );
  }

  const m = detail.msg;
  const trigger = m.label
    ? today.apps.flatMap((a) => a.windows).find((w) => w.title === m.label)
    : undefined;
  return (
    <Drawer
      chip={
        <Chip tone={m.kind === "distraction" ? "critical" : m.kind === "idle" ? "warning" : "accent"} icon={KIND_ICON[m.kind]}>
          {KIND_LABEL[m.kind] ?? m.kind}
        </Chip>
      }
      title="Sent to you"
      meta={`${clock(m.created_at)} · ${ago(m.created_at, now)}`}
      onClose={onClose}
    >
      <div className="quote">{m.text}</div>
      {m.label && (
        <>
          <SectionTitle>What triggered it</SectionTitle>
          <WindowList items={[trigger ?? { app: "Window", title: m.label, site: null, flag: null, secs: 0 }]} />
        </>
      )}
    </Drawer>
  );
}
