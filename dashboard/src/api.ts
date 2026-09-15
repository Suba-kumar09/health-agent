import { buildMockSummary } from "./mockData";
import type { DashboardSummary } from "./types";

// No read endpoint exists on the backend yet (server/routes only has
// /goal, /v1/enroll, /v1/ingest, /v1/messages/pending — all write/ingest
// oriented). Once a GET /v1/me/summary is added server-side, swap the body
// of this function for a fetch() against it; DashboardSummary already
// mirrors the backend models so the rest of the app shouldn't need to change.
export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  return buildMockSummary();
}
