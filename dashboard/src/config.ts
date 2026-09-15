// system_name is how server/routes/dashboard.py looks up "which employee" -
// there's no auth/session system anywhere in this project yet, so this has
// to be the machine's real hostname, matching how /goal and enrollment
// already resolve employees (server/auth.py's resolve_employee_by_system_name).
// Set both via dashboard/.env (see .env.example).
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8001";
export const SYSTEM_NAME = import.meta.env.VITE_SYSTEM_NAME ?? "";
