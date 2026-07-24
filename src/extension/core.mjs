export const BVID = "BV1ZW42197oE";
export const BACKEND_URL = "http://127.0.0.1:8765";

export function progressKey(bvid = BVID) {
  return `video2skill:${bvid}`;
}

export function isTargetPage(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname === "www.bilibili.com" && new RegExp(`/video/${BVID}(?:/|$)`).test(parsed.pathname);
  } catch {
    return false;
  }
}

export function panelOptions(url) {
  return isTargetPage(url) ? { path: "sidepanel.html", enabled: true } : { enabled: false };
}

export function emptyProgress() {
  return { currentStep: 0, passed: [false, false, false, false], errors: { count: 0, types: {} } };
}

function normalizedProgress(progress = {}) {
  const base = emptyProgress();
  return {
    currentStep: Number.isInteger(progress.currentStep) ? Math.max(0, Math.min(3, progress.currentStep)) : base.currentStep,
    passed: Array.from({ length: 4 }, (_, index) => Boolean(progress.passed?.[index])),
    errors: { count: Number.isInteger(progress.errors?.count) ? Math.max(0, progress.errors.count) : 0, types: { ...(progress.errors?.types ?? {}) } },
  };
}

export function reduceProgress(progress, action) {
  const next = normalizedProgress(progress);
  const step = Math.max(0, Math.min(3, Number(action.step) || 0));
  if (action.type === "PASS") {
    next.passed[step] = true;
    next.currentStep = next.passed.findIndex((passed) => !passed);
    if (next.currentStep === -1) next.currentStep = 3;
  }
  if (action.type === "FAIL") {
    const type = action.errorType || "test";
    next.currentStep = step;
    next.errors.count += 1;
    next.errors.types[type] = (next.errors.types[type] || 0) + 1;
  }
  if (action.type === "SELECT") next.currentStep = step;
  return next;
}

export function gradeAnswer(step, selectedOptionId) {
  return {
    passed: Boolean(selectedOptionId) && selectedOptionId === step.correctOptionId,
    errorType: "answer",
  };
}

export function stageEntries(job) {
  const stageNames = ["download", "transcribe", "frames", "compile", "validate"];
  return stageNames.map((name) => ({ name, ...(job?.stages?.[name] ?? { state: "pending" }) }));
}
