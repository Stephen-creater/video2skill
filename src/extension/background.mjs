import { isTargetPage, panelOptions } from "./core.mjs";

async function syncPanel(tabId, url) {
  await chrome.sidePanel.setOptions({ tabId, ...panelOptions(url) });
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url || changeInfo.status === "loading") {
    syncPanel(tabId, tab.url).catch(() => {});
  }
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId).then((tab) => syncPanel(tabId, tab.url)).catch(() => {});
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "OPEN_PANEL" || !sender.tab?.id || !isTargetPage(sender.tab.url)) return;
  (async () => {
    await syncPanel(sender.tab.id, sender.tab.url);
    await chrome.sidePanel.open({ tabId: sender.tab.id });
  })().catch(() => {});
});
