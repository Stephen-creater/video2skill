import { BVID, isTargetPage } from "./core.mjs";

if (isTargetPage(location.href)) {
  const button = document.createElement("button");
  button.className = "video2skill-start";
  button.textContent = "开始练习";
  button.addEventListener("click", () => chrome.runtime.sendMessage({ type: "OPEN_PANEL", bvid: BVID }));
  const style = document.createElement("style");
  style.textContent = ".video2skill-start{position:fixed;right:24px;bottom:92px;z-index:99999;border:0;border-radius:999px;background:#00aeec;color:#fff;padding:10px 16px;font:600 14px system-ui;box-shadow:0 6px 20px #0004;cursor:pointer}.video2skill-start:hover{background:#008ec5}";
  document.documentElement.append(style, button);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "SEEK_VIDEO" || !isTargetPage(location.href)) return;
  const video = document.querySelector("video");
  if (!video) return;
  video.currentTime = Number(message.seconds) || 0;
  video.play().catch(() => {});
});
