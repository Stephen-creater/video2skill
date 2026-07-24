import { BACKEND_URL, BVID, emptyProgress, gradeAnswer, progressKey, reduceProgress, stageEntries } from "./core.mjs";

const $ = (selector) => document.querySelector(selector);
const state = { skill: null, progress: emptyProgress(), step: 0 };
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
  $("#question").textContent = step.question;
  $("#hint").textContent = step.hint;
  $("#failure").textContent = step.failureExplanation;
  $("#answers").replaceChildren(...step.options.map((option) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = option.id;
    label.append(input, document.createTextNode(option.text));
    return label;
  }));
  $("#lesson").hidden = false;
  $("#result").hidden = true;
  renderSteps();
}

async function checkAnswer() {
  const selected = document.querySelector('input[name="answer"]:checked')?.value;
  if (!selected) {
    $("#status").textContent = "请先选择答案。";
    return;
  }
  const outcome = gradeAnswer(state.skill.steps[state.step], selected);
  await save(outcome.passed
    ? { type: "PASS", step: state.step }
    : { type: "FAIL", step: state.step, errorType: outcome.errorType });
  $("#status").textContent = outcome.passed ? "回答正确。" : "回答错误，可查看提示或返回视频。";
  $("#result").hidden = false;
  $("#result").textContent = outcome.passed ? "✓ 已通过" : state.skill.steps[state.step].failureExplanation;
  renderSteps();
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
$("#check").onclick = checkAnswer;
$("#regenerate").onclick = regenerate;
boot().catch((error) => { $("#status").textContent = `本地 Skill 不可用：${error.message}`; });
