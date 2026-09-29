import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import { Donut } from "../charts/Donut";
import { DayTimeline } from "../charts/DayTimeline";
import { TrendChart } from "../charts/TrendChart";
import { ago, duration, initials, STATE_LABEL, STATUS_LABEL, windowSource, windowTitle } from "../format";
import { useNow, usePolling } from "../hooks";
import type { EmployeeDetail, EmployeeRow, Overview, SegmentState, Site, Status } from "../types";
import {
  Chip,
  HBars,
  KIND_ICON,
  Kpi,
  PrivacyNote,
  SectionTitle,
  StateChip,
  StatusChip,
  StatusPill,
  TotalsTiles,
  WindowList,
} from "../ui/bits";
import { Drawer } from "../ui/Drawer";
import { AlertIcon, ChevronIcon } from "../ui/icons";

type Detail =
  | { type: "employee"; id: string }
  | { type: "site"; keyword: string }
  | { type: "category"; state: SegmentState };

const ORDER: Record<Status, number> = { distraction: 0, active: 1, idle: 2, locked: 3, offline: 4, no_device: 5 };

export function AdminPage() {
  const overview = usePolling(api.fetchOverview, 15_000);
  const now = useNow(30_000);
  const [detail, setDetail] = useState<Detail | null>(null);
  const close = useCallback(() => setDetail(null), []);

  const o = overview.data;
  if (!o) {
    return overview.error ? (
      <div className="banner">{overview.error}</div>
    ) : (
      <div className="loading">Loading your organization…</div>
    );
  }
  const serverNow = Math.max(o.now, now);
  const roster = [...o.employees].sort(
    (a, b) => ORDER[a.status.status] - ORDER[b.status.status] || a.name.localeCompare(b.name),
  );

  return (
    <>
      {overview.error && <div className="banner">Couldn't refresh: {overview.error} Showing the last data loaded.</div>}

      <div className="kpi-row">
        <Kpi label="Active now" value={o.kpis.active} sub={`of ${o.kpis.total} employees`} chip={<StatusChip status="active" text="Working" />} />
        <Kpi label="Idle or away" value={o.kpis.idle} sub="no input, or screen locked" chip={<StatusChip status="idle" text="Watch" />} />
        <Kpi label="Distracted" value={o.kpis.distraction} sub="on a flagged site right now" chip={<StatusChip status="distraction" text="Alert" />} />
        <Kpi label="Offline" value={o.kpis.offline} sub="agent not reporting" chip={<StatusChip status="offline" text="No signal" />} />
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head">
            <h3>Org activity, last 24h</h3>
            <span className="sub">active minutes per hour, all employees</span>
          </div>
          <TrendChart points={o.trend} />
        </div>
        <div className="card">
          <div className="card-head">
            <h3>Time &amp; focus</h3>
            <span className="sub">today · click a row</span>
          </div>
          <Donut totals={o.totals} onOpen={(state) => setDetail({ type: "category", state })} />
        </div>
      </div>

      {/* No org-wide notification feed on purpose: with hundreds of people it
          is noise. Each person's notifications are in their own details panel. */}
      <div className="grid-1">
        <div className="card">
          <div className="card-head">
            <h3>Top distracting sites</h3>
            <span className="sub">today · click to see what was watched</span>
          </div>
          <HBars
            empty="No distracting sites today."
            rows={o.distracting_sites.map((s) => ({
              key: s.keyword,
              name: s.name,
              secs: s.secs,
              tip: (
                <>
                  <b>{s.name}</b> · {duration(s.secs)}
                  {s.rows[0] && (
                    <em>
                      Most: {s.rows[0].employee_name}
                      {s.rows[0].title ? ` — ${s.rows[0].title}` : ""}
                    </em>
                  )}
                </>
              ),
            }))}
            onOpen={(keyword) => setDetail({ type: "site", keyword })}
          />
        </div>
      </div>

      <div className="section-head">
        <h2>Team status</h2>
        <span className="hint">Click an employee to see what's on their screen and their day</span>
      </div>
      <div className="card rtable-wrap">
        {roster.length === 0 ? (
          <div className="empty">
            No employees yet. Add one with <code>python -m server.admin_cli add-employee</code>.
          </div>
        ) : (
          <table className="roster">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Status</th>
                <th className="col-screen">On screen now</th>
                <th>Last active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {roster.map((e) => (
                <RosterRow key={e.employee_id} e={e} now={serverNow} onOpen={() => setDetail({ type: "employee", id: e.employee_id })} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail && <AdminDetail detail={detail} overview={o} now={serverNow} onOpen={setDetail} onClose={close} />}
    </>
  );
}

function RosterRow({ e, now, onOpen }: { e: EmployeeRow; now: number; onOpen: () => void }) {
  const s = e.status;
  const live = s.status !== "offline" && s.status !== "no_device";
  return (
    <tr
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          onOpen();
        }
      }}
    >
      <td>
        <div className="person">
          <span className="avatar">{initials(e.name)}</span>
          <span>{e.name}</span>
        </div>
      </td>
      <td>
        <StatusPill status={s.status} />
      </td>
      <td className="col-screen">
        {live && s.on_screen ? (
          <div className="onscreen">
            <b>{windowSource(s.on_screen)}</b>
            <span>{windowTitle(s.on_screen)}</span>
          </div>
        ) : (
          <span className="muted-cell">—</span>
        )}
      </td>
      <td className="muted-cell">
        {s.status === "active" || s.status === "distraction" ? "now" : ago(e.last_active_at, now)}
      </td>
      <td className="chev">
        <ChevronIcon />
      </td>
    </tr>
  );
}

interface DetailProps {
  detail: Detail;
  overview: Overview;
  now: number;
  onOpen: (d: Detail) => void;
  onClose: () => void;
}

function AdminDetail({ detail, overview, now, onOpen, onClose }: DetailProps) {
  if (detail.type === "employee") {
    return <EmployeeDrawer id={detail.id} overview={overview} now={now} onClose={onClose} />;
  }

  if (detail.type === "site") {
    const site: Site | undefined = overview.distracting_sites.find((s) => s.keyword === detail.keyword);
    if (!site) return null;
    const people = new Set(site.rows.map((r) => r.employee_id)).size;
    return (
      <Drawer
        chip={<Chip tone="critical" icon={<AlertIcon />}>Flagged site</Chip>}
        title={site.name}
        meta={`${duration(site.secs)} today · ${people} ${people === 1 ? "person" : "people"}`}
        onClose={onClose}
      >
        <SectionTitle>Who watched what</SectionTitle>
        {site.rows.map((r, i) => (
          <button className="item" key={i} onClick={() => onOpen({ type: "employee", id: r.employee_id })}>
            <div className="app-tile">{initials(r.employee_name)}</div>
            <div>
              <div className="t">{r.title ?? r.site ?? site.name}</div>
              <div className="s">
                {r.employee_name}
                {r.site ? ` · ${r.site}` : ""}
              </div>
            </div>
            <div className="d">{duration(r.secs)}</div>
          </button>
        ))}
        <PrivacyNote titlesHidden={!overview.show_titles} />
      </Drawer>
    );
  }

  if (detail.type === "category") {
    const k = detail.state;
    const rows = overview.employees.filter((e) => e.totals[k] > 0).sort((a, b) => b.totals[k] - a.totals[k]);
    return (
      <Drawer chip={<StateChip state={k} />} title={`${duration(overview.totals[k])} today`} meta="Across all employees" onClose={onClose}>
        <SectionTitle>By employee</SectionTitle>
        {rows.length === 0 && <div className="empty">Nobody has {STATE_LABEL[k].toLowerCase()} time today.</div>}
        {rows.map((e) => (
          <button className="item" key={e.employee_id} onClick={() => onOpen({ type: "employee", id: e.employee_id })}>
            <div className="app-tile">{initials(e.name)}</div>
            <div>
              <div className="t">{e.name}</div>
              <div className="s">{STATUS_LABEL[e.status.status]}</div>
            </div>
            <div className="d">{duration(e.totals[k])}</div>
          </button>
        ))}
      </Drawer>
    );
  }

  return null;
}

function EmployeeDrawer({ id, overview, now, onClose }: { id: string; overview: Overview; now: number; onClose: () => void }) {
  const [data, setData] = useState<EmployeeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const row = overview.employees.find((e) => e.employee_id === id);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .fetchEmployee(id)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [id]);

  const e = data ?? row;
  if (!e) return null;
  const s = e.status;
  const live = s.status !== "offline" && s.status !== "no_device";
  const sinceText = live && s.since != null ? ` · ${duration(now - s.since)}` : "";

  return (
    <Drawer
      chip={<StatusChip status={s.status} text={`${STATUS_LABEL[s.status]}${sinceText}`} />}
      title={e.name}
      meta={`${e.system_name}${e.email ? ` · ${e.email}` : ""} · last active ${live && (s.status === "active" || s.status === "distraction") ? "now" : ago(e.last_active_at, now)}`}
      onClose={onClose}
    >
      {s.on_screen && (
        <div className="now-card">
          <div className="app-tile">{s.on_screen.app.slice(0, 2).toUpperCase()}</div>
          <div>
            <div className="s">
              {s.status === "offline" ? "Last on screen" : s.status === "idle" || s.status === "locked" ? "On screen when they stepped away" : "On screen now"}
            </div>
            <div className="t">{windowTitle(s.on_screen)}</div>
            <div className="s">{windowSource(s.on_screen)}</div>
          </div>
        </div>
      )}
      <SectionTitle>Today</SectionTitle>
      <TotalsTiles totals={e.totals} target={overview.workday_secs} />

      {error && <div className="note">Couldn't load the full day: {error}</div>}
      {!data && !error && <div className="empty">Loading their day…</div>}
      {data && (
        <>
          {data.segments.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <DayTimeline
                segments={data.segments}
                dayStart={overview.day_start}
                now={now}
                workdaySecs={overview.workday_secs}
                compact
              />
            </div>
          )}
          <SectionTitle>Windows and tabs today</SectionTitle>
          <WindowList items={data.windows} empty="No activity captured today." />
          {/* The server returns at most the latest 20. */}
          <SectionTitle>
            Notifications sent
            {data.messages.length >= 20 ? " · latest 20" : data.messages.length ? ` (${data.messages.length})` : ""}
          </SectionTitle>
          {data.messages.length === 0 && <div className="empty">No notifications sent to {e.name.split(" ")[0]} yet.</div>}
          {data.messages.length > 0 && (
            <>
              {data.messages.map((m) => (
                <div className="item" key={m.message_id}>
                  <div className={`feed-icon ${m.kind}`}>{KIND_ICON[m.kind]}</div>
                  <div>
                    <div className="t plain">{m.text}</div>
                    {m.label && <div className="s">About: {m.label}</div>}
                  </div>
                  <div className="d">{ago(m.created_at, now)}</div>
                </div>
              ))}
            </>
          )}
          <PrivacyNote titlesHidden={!data.show_titles} />
        </>
      )}
    </Drawer>
  );
}
