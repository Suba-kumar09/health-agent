import type { ReactNode } from "react";
import { ago, duration, hoursLabel, KIND_LABEL, STATE_LABEL, STATUS_LABEL, windowSource, windowTitle } from "../format";
import type { Message, MessageKind, SegmentState, Status, Totals, WindowItem } from "../types";
import { AlertIcon, ClockIcon, CupIcon, DotIcon, LockIcon, OffIcon, ShieldIcon } from "./icons";
import { useTooltip } from "./Tooltip";

export const STATES: SegmentState[] = ["active", "distraction", "idle", "locked"];

const STATUS_CHIP: Record<Status, string> = {
  active: "good",
  distraction: "critical",
  idle: "warning",
  locked: "neutral",
  offline: "neutral",
  no_device: "neutral",
};

const STATUS_ICON: Record<Status, ReactNode> = {
  active: <DotIcon />,
  distraction: <AlertIcon />,
  idle: <ClockIcon />,
  locked: <LockIcon />,
  offline: <OffIcon />,
  no_device: <OffIcon />,
};

// Status color always comes with an icon and a word, never color alone.
export function StatusChip({ status, text }: { status: Status; text?: string }) {
  return (
    <span className={`chip ${STATUS_CHIP[status]}`}>
      {STATUS_ICON[status]}
      {text ?? STATUS_LABEL[status]}
    </span>
  );
}

export function StateChip({ state }: { state: SegmentState }) {
  return <StatusChip status={state} text={STATE_LABEL[state]} />;
}

export function Chip({ tone, icon, children }: { tone: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={`chip ${tone}`}>
      {icon}
      {children}
    </span>
  );
}

export function StatusPill({ status }: { status: Status }) {
  return (
    <span className={`status-pill ${status}`}>
      <span className="dot" />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Kpi({ label, value, sub, chip }: { label: string; value: ReactNode; sub: string; chip: ReactNode }) {
  return (
    <div className="card kpi">
      <div className="top">
        <span className="label">{label}</span>
        {chip}
      </div>
      <span className="value">{value}</span>
      <span className="label small" title={sub}>
        {sub}
      </span>
    </div>
  );
}

// Active + Distraction + Idle + Locked, then their sum as Total -- how the
// tracked day was spent, with the whole-day figure alongside the parts.
export function TotalsTiles({
  totals,
  totalLabel = "Total",
  target,
}: {
  totals: Totals;
  totalLabel?: string;
  target?: number; // the workday length in seconds, e.g. 8h
}) {
  const total = STATES.reduce((sum, k) => sum + totals[k], 0);
  const progress = target ? Math.min(100, (total / target) * 100) : null;
  return (
    <div className="totals">
      {STATES.map((k) => (
        <div className="total-tile" key={k}>
          <span className="total-name">
            <span className={`legend-dot dot-${k}`} />
            {STATE_LABEL[k]}
          </span>
          <b>{duration(totals[k])}</b>
        </div>
      ))}
      <div className="total-tile sum">
        <span className="total-name">{totalLabel}</span>
        <b>
          {duration(total)}
          {target ? <small> of {hoursLabel(target)}</small> : null}
        </b>
        {progress != null && (
          <span
            className="total-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
            aria-label={`${Math.round(progress)}% of the ${hoursLabel(target!)} workday`}
          >
            <span style={{ width: `${progress}%` }} />
          </span>
        )}
      </div>
    </div>
  );
}

export function LegendDot({ state }: { state: SegmentState }) {
  return <span className={`legend-dot dot-${state}`} />;
}

export function appInitials(app: string): string {
  const words = app.replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase();
}

// Rows of "window title / app · site / duration", used in every details panel.
export function WindowList({ items, empty }: { items: WindowItem[]; empty?: string }) {
  if (items.length === 0) return <div className="empty">{empty ?? "Nothing captured."}</div>;
  return (
    <div>
      {items.map((w, i) => (
        <div className="item" key={`${w.app}|${w.title}|${i}`}>
          <div className="app-tile" aria-hidden="true">
            {appInitials(w.app)}
          </div>
          <div>
            <div className="t">{windowTitle(w)}</div>
            <div className="s">
              <span>{windowSource(w)}</span>
              {w.flag && <span className="flag">Flagged: {w.flag}</span>}
            </div>
          </div>
          <div className="d">{duration(w.secs)}</div>
        </div>
      ))}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h4 className="d-h">{children}</h4>;
}

export function PrivacyNote({ titlesHidden }: { titlesHidden?: boolean }) {
  return (
    <div className="privacy">
      <ShieldIcon />
      <span>
        {titlesHidden
          ? "Window titles are hidden from admins by your organization's settings. Only app names and sites are shown."
          : "Window and tab titles come from the agent's window and browser watchers. Share them only with people the employee agreed to."}
      </span>
    </div>
  );
}

export const KIND_ICON: Record<MessageKind, ReactNode> = {
  break: <CupIcon />,
  idle: <ClockIcon />,
  distraction: <AlertIcon />,
};

export function MessageFeed({
  messages,
  now,
  showWho,
  onOpen,
  empty,
}: {
  messages: Message[];
  now: number;
  showWho: boolean;
  onOpen: (m: Message) => void;
  empty: string;
}) {
  if (messages.length === 0) return <div className="empty">{empty}</div>;
  return (
    <div className="feed">
      {messages.map((m) => (
        <button className="feed-row" key={m.message_id} onClick={() => onOpen(m)}>
          <span className={`feed-icon ${m.kind}`}>{KIND_ICON[m.kind] ?? <DotIcon />}</span>
          <span className="feed-body">
            <span className="line1">
              <span className="name">{showWho ? (m.employee_name ?? "Unknown") : (KIND_LABEL[m.kind] ?? m.kind)}</span>
              <time>{ago(m.created_at, now)}</time>
            </span>
            <span className="msg">{m.text}</span>
            {m.label && <span className="about">About: {m.label}</span>}
          </span>
        </button>
      ))}
    </div>
  );
}

export interface BarRow {
  key: string;
  name: string;
  secs: number;
  tip: ReactNode;
}

export function HBars({ rows, onOpen, empty }: { rows: BarRow[]; onOpen: (key: string) => void; empty: string }) {
  const { tipProps } = useTooltip();
  if (rows.length === 0) return <div className="empty">{empty}</div>;
  const max = Math.max(...rows.map((r) => r.secs), 1);
  return (
    <div className="hbars">
      {rows.map((r) => (
        <button className="hbar-row" key={r.key} onClick={() => onOpen(r.key)} {...tipProps(r.tip)}>
          <span className="name">{r.name}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ width: `${Math.max(3, (r.secs / max) * 100)}%` }} />
          </span>
          <span className="val">{duration(r.secs)}</span>
        </button>
      ))}
    </div>
  );
}
