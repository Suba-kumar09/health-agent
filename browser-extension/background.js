// Sends {url, title, ts} for the active tab to the local agent's browser
// bridge whenever the active tab or its URL changes. Requires pairing first
// (see options.html) -- silently no-ops until bridgePort/bridgeToken exist
// in storage, since there is nothing useful to do (and nothing to trust)
// before that.

async function getPairing() {
  const { bridgePort, bridgeToken } = await chrome.storage.local.get(["bridgePort", "bridgeToken"]);
  if (!bridgePort || !bridgeToken) return null;
  return { bridgePort, bridgeToken };
}

async function sendTabEvent(tab) {
  if (!tab || !tab.url || !tab.url.startsWith("http")) return; // skip chrome://, about:, etc.

  const pairing = await getPairing();
  if (!pairing) return;

  const payload = { url: tab.url, title: tab.title || "", ts: Date.now() / 1000 };

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
  } catch (err) {
    // Agent likely offline/not running -- expected during normal use, not an error.
    console.debug("health-agent bridge: unreachable", err);
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
