// Sends {url, title, ts} for the active tab to the local agent's browser
// bridge whenever the active tab or its URL changes. Requires pairing first
// (see options.html) -- silently no-ops until bridgePort/bridgeToken exist
// in storage, since there is nothing useful to do (and nothing to trust)
// before that.
//
// All state (last-sent event, offline queue) lives in chrome.storage.local
// rather than module-level variables, since MV3 background service workers
// are not persistent -- Chrome can kill and restart this script at any time,
// and in-memory state would silently reset.

const DEFAULT_PRIVACY_SETTINGS = {
  enabled: true,
  stripQueryStrings: true,
  skipIncognito: true,
  denylist: [],
};

const MAX_QUEUE_SIZE = 20;

async function getPairing() {
  const { bridgePort, bridgeToken } = await chrome.storage.local.get(["bridgePort", "bridgeToken"]);
  if (!bridgePort || !bridgeToken) return null;
  return { bridgePort, bridgeToken };
}

async function getPrivacySettings() {
  const { privacySettings } = await chrome.storage.local.get("privacySettings");
  return { ...DEFAULT_PRIVACY_SETTINGS, ...(privacySettings || {}) };
}

function isDenylisted(url, denylist) {
  if (denylist.length === 0) return false;
  const hostname = new URL(url).hostname.toLowerCase();
  return denylist.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
}

function stripQueryString(url) {
  const u = new URL(url);
  u.search = "";
  return u.toString();
}

async function getLastSent() {
  const { lastSent } = await chrome.storage.local.get("lastSent");
  return lastSent || null;
}

async function setLastSent(entry) {
  await chrome.storage.local.set({ lastSent: entry });
}

async function getQueue() {
  const { offlineQueue } = await chrome.storage.local.get("offlineQueue");
  return offlineQueue || [];
}

async function setQueue(queue) {
  await chrome.storage.local.set({ offlineQueue: queue.slice(-MAX_QUEUE_SIZE) });
}

async function enqueue(payload) {
  const queue = await getQueue();
  queue.push(payload);
  await setQueue(queue);
}

// Returns true on a confirmed 200 from the agent, false on anything else
// (unreachable, rejected, etc.) -- callers decide what to do with a false.
async function postTabEvent(pairing, payload) {
  try {
    const resp = await fetch(`http://127.0.0.1:${pairing.bridgePort}/tab-event`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${pairing.bridgeToken}`,
      },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      console.warn("health-agent bridge: tab-event rejected", resp.status);
    }
    return resp.ok;
  } catch (err) {
    // Agent likely offline/not running -- expected during normal use, not an error.
    console.debug("health-agent bridge: unreachable", err);
    return false;
  }
}

// Opportunistic: attempts to drain the offline queue whenever we're about to
// talk to the agent anyway. Not a background retry loop -- if the agent is
// still unreachable, the queue just keeps growing (capped) until it comes back.
async function flushQueue(pairing) {
  const queue = await getQueue();
  if (queue.length === 0) return;

  const remaining = [];
  for (const payload of queue) {
    const ok = await postTabEvent(pairing, payload);
    if (!ok) remaining.push(payload);
  }
  await setQueue(remaining);
}

async function sendTabEvent(tab) {
  if (!tab || !tab.url || !tab.url.startsWith("http")) return; // skip chrome://, about:, etc.

  const pairing = await getPairing();
  if (!pairing) return;

  const settings = await getPrivacySettings();
  if (!settings.enabled) return;
  if (settings.skipIncognito && tab.incognito) return;
  if (isDenylisted(tab.url, settings.denylist)) return;

  const url = settings.stripQueryStrings ? stripQueryString(tab.url) : tab.url;
  const title = tab.title || "";

  const last = await getLastSent();
  if (last && last.url === url && last.title === title) return; // no real change -- skip

  const payload = { url, title, ts: Date.now() / 1000 };

  await flushQueue(pairing);
  const ok = await postTabEvent(pairing, payload);
  if (ok) {
    await setLastSent({ url, title });
  } else {
    await enqueue(payload);
  }
}

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);
  sendTabEvent(tab);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" || changeInfo.url) {
    sendTabEvent(tab);
  }
});
