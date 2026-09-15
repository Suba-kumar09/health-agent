import type { ConsentSettings } from "./types";

// Today/History/Goals are wired to real server/routes/dashboard.py endpoints
// (see api.ts). Consent/capture-mode/collector state has no server-side
// record at all - that's agent-local state (config.toml, consent.json) - so
// it stays on mock data until a local read route exists.
export function buildMockConsentSettings(): ConsentSettings {
  return {
    basicConsentedAt: Math.floor(Date.now() / 1000) - 21 * 24 * 3600,
    detailedConsentedAt: null,
    captureMode: "aggregate",
    encryptAtRest: true,
    collectors: [
      { name: "input_watcher", label: "Keyboard & mouse activity (counts only)", enabled: true },
      { name: "window_watcher", label: "Active app / window title", enabled: true },
      { name: "afk", label: "Away-from-keyboard detection", enabled: true },
      { name: "browser_bridge", label: "Active browser tab (via extension)", enabled: true },
    ],
  };
}
