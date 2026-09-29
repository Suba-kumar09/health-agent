// Mirrors the server's response models (server/dashboard_views.py,
// server/routes/dashboard.py, server/routes/admin.py, server/routes/auth.py).
// Field names stay snake_case exactly as the API sends them.

export type SegmentState = "active" | "distraction" | "idle" | "locked";
export type Status = SegmentState | "offline" | "no_device";
export type MessageKind = "break" | "distraction" | "idle";

export interface Account {
  employee_id: string;
  name: string;
  role: "admin" | "employee";
  email: string | null;
  system_name: string;
}

export interface WindowItem {
  app: string;
  title: string | null; // null when the organization hides titles from admins
  site: string | null;
  flag: string | null; // distraction keyword it matched, e.g. "youtube"
  secs: number;
}

export interface Segment {
  state: SegmentState;
  start_ts: number;
  end_ts: number;
  windows: WindowItem[];
}

export interface Totals {
  active: number;
  distraction: number;
  idle: number;
  locked: number;
}

export interface HourBlock {
  hour_start: number;
  totals: Totals;
  windows: WindowItem[];
}

export interface Message {
  message_id: string;
  kind: MessageKind;
  text: string;
  created_at: number;
  label: string | null;
  employee_id: string | null;
  employee_name: string | null;
}

export interface StatusInfo {
  status: Status;
  since: number | null;
  last_seen_at: number | null;
  on_screen: WindowItem | null;
}

export interface Goal {
  text: string;
  created_at: number;
  deadline_at: number;
}

export interface AppUsage {
  app: string;
  secs: number;
  windows: WindowItem[];
}

export interface Today {
  now: number;
  day_start: number;
  workday_secs: number;
  employee_name: string;
  device_name: string | null;
  status: StatusInfo;
  totals: Totals;
  segments: Segment[];
  hours: HourBlock[];
  apps: AppUsage[];
  goal: Goal | null;
  messages: Message[];
}

export interface Day {
  date: string;
  day_start: number;
  totals: Totals;
  top_windows: WindowItem[];
  flagged_windows: WindowItem[];
}

export interface EmployeeRow {
  employee_id: string;
  name: string;
  email: string | null;
  system_name: string;
  role: string;
  status: StatusInfo;
  last_active_at: number | null;
  totals: Totals;
}

export interface Site {
  keyword: string;
  name: string;
  secs: number;
  rows: { employee_id: string; employee_name: string; title: string | null; site: string | null; secs: number }[];
}

export interface Overview {
  now: number;
  day_start: number;
  workday_secs: number;
  show_titles: boolean;
  kpis: { total: number; active: number; distraction: number; idle: number; offline: number };
  employees: EmployeeRow[];
  totals: Totals;
  trend: { hour_start: number; active_secs: number }[];
  distracting_sites: Site[];
  messages: Message[];
}

export interface EmployeeDetail extends EmployeeRow {
  show_titles: boolean;
  windows: WindowItem[];
  segments: Segment[];
  hours: HourBlock[];
  messages: Message[];
}
