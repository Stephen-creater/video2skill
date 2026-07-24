import { isTargetPage } from "./core.mjs";

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "OPEN_PANEL" || !sender.tab?.id || !isTargetPage(sender.tab.url)) return;
  chrome.sidePanel.setOptions({ tabId: sender.tab.id, path: "sidepanel.html", enabled: true });
  chrome.sidePanel.open({ tabId: sender.tab.id });
});
