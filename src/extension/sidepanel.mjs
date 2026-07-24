import { createPlayground } from "./vendor/livecodes.js";
import { BACKEND_URL, BVID, emptyProgress, normalizeTestResult, progressKey, reduceProgress, skillConfig, stageEntries } from "./core.mjs";

const $ = (selector) => document.querySelector(selector);
const state = { skill: null, progress: emptyProgress(), playground: null, step: 0 };
const storageKey = progressKey(BVID);

async function save(action) {
  state.progress = reduceProgress(state.progress, action);
  await chrome.storage.local.set({ [storageKey]: state.progress });
}

async function seek(seconds) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: "SEEK_VIDEO", seconds });
}

function renderSteps() {
  $("#steps").replaceChildren(...state.skill.steps.map((step, index) => {
    const item = document.createElement("li");
    item.textContent = `${index + 1}. ${step.title}`;
    item.className = `${index === state.step ? "active" : ""} ${state.progress.passed[index] ? "done" : ""}`;
    item.onclick = () => selectStep(index);
    return item;
  }));
}

async function selectStep(index) {
  state.step = index;
  const step = state.skill.steps[index];
  await save({ type: "SELECT", step: index });
  $("#title").textContent = step.title;
  $("#task").textContent = step.requirement;
  $("#hint").textContent = step.hint;
  $("#failure").textContent = step.failureExplanation;
  $("#lesson").hidden = false;
  renderSteps();
  const config = skillConfig(step);
  if (!state.playground) {
    state.playground = await createPlayground($("#playground"), {
      appUrl: "http://127.0.0.1:8765/livecodes/",
      config,
      loading: "eager",
    });
  }
  await state.playground.setConfig(config);
}

async function checkCode() {
  try {
    await state.playground.getCode();
    const outcome = normalizeTestResult(await state.playground.runTests());
    await save(outcome.passed
      ? { type: "PASS", step: state.step }
      : { type: "FAIL", step: state.step, errorType: outcome.errorType });
    $("#status").textContent = outcome.passed ? "通过，继续下一步。" : "未通过：请根据失败解释调整后再试。";
    renderSteps();
  } catch (error) {
    await save({ type: "FAIL", step: state.step, errorType: "runtime" });
    $("#status").textContent = `检查失败：${error.message}`;
  }
}

function renderJob(job) {
  $("#job").hidden = false;
  $("#stages").replaceChildren(...stageEntries(job).map(({ name, state: stageState, error }) => {
    const item = document.createElement("li");
    item.className = `state-${stageState}`;
    item.textContent = `${name}: ${stageState}${error ? ` — ${error}` : ""}`;
    return item;
  }));
}

async function regenerate() {
  $("#regenerate").disabled = true;
  try {
    const response = await fetch(`${BACKEND_URL}/v1/compile`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ bvid: BVID }) });
    if (!response.ok) throw new Error(`compile ${response.status}`);
    const { jobId } = await response.json();
    for (;;) {
      const jobResponse = await fetch(`${BACKEND_URL}/v1/jobs/${jobId}`);
      if (!jobResponse.ok) throw new Error(`job ${jobResponse.status}`);
      const job = await jobResponse.json();
      renderJob(job);
      if (job.status === "completed" || job.status === "failed") {
        $("#status").textContent = job.status === "completed" ? "重新生成完成，固定 Skill 已可继续练习。" : "生成失败；本地固定 Skill 仍可继续使用。";
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
  } catch (error) {
    $("#status").textContent = `无法重新生成；固定 Skill 仍可继续使用（${error.message}）。`;
  } finally {
    $("#regenerate").disabled = false;
  }
}

async function boot() {
  const stored = await chrome.storage.local.get(storageKey);
  state.progress = stored[storageKey] ?? emptyProgress();
  const response = await fetch(`${BACKEND_URL}/v1/skills/${BVID}`);
  if (!response.ok) throw new Error(`skill ${response.status}`);
  state.skill = await response.json();
  state.step = state.progress.currentStep;
  renderSteps();
  await selectStep(state.step);
  $("#status").textContent = "固定 Skill 已加载。";
}

$("#jump").onclick = () => seek(state.skill.steps[state.step].videoSeconds);
$("#check").onclick = checkCode;
$("#regenerate").onclick = regenerate;
boot().catch((error) => { $("#status").textContent = `本地 Skill 不可用：${error.message}`; });
