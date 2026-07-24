import test from "node:test";
import assert from "node:assert/strict";

import {
  gradeAnswer,
  progressKey,
  reduceProgress,
  isTargetPage,
  panelOptions,
  stageEntries,
} from "../src/extension/core.mjs";

const BVID = "BV1ZW42197oE";

test("only the target Bilibili page is supported", () => {
  assert.equal(isTargetPage(`https://www.bilibili.com/video/${BVID}/`), true);
  assert.equal(isTargetPage("https://www.bilibili.com/video/BV0000000000/"), false);
});

test("progress is isolated by target BVID and survives serialized storage", () => {
  assert.equal(progressKey(BVID), `video2skill:${BVID}`);
  const next = reduceProgress({}, { type: "FAIL", step: 2, errorType: "answer" });
  assert.deepEqual(JSON.parse(JSON.stringify(next)), {
    currentStep: 2,
    passed: [false, false, false, false],
    errors: { count: 1, types: { answer: 1 } },
  });
});

test("answers are checked deterministically", () => {
  const step = { correctOptionId: "b" };
  assert.deepEqual(gradeAnswer(step, "b"), { passed: true, errorType: "answer" });
  assert.deepEqual(gradeAnswer(step, "a"), { passed: false, errorType: "answer" });
  assert.deepEqual(gradeAnswer(step), { passed: false, errorType: "answer" });
});

test("passing a step advances to the next incomplete step", () => {
  assert.deepEqual(reduceProgress({}, { type: "PASS", step: 0 }), {
    currentStep: 1,
    passed: [true, false, false, false],
    errors: { count: 0, types: {} },
  });
});

test("backend stages use real API shapes", () => {
  assert.deepEqual(stageEntries({ stages: { download: { state: "completed" } } }).map((stage) => stage.state), ["completed", "pending", "pending", "pending", "pending"]);
});

test("side panel is target-scoped", () => {
  assert.deepEqual(panelOptions(`https://www.bilibili.com/video/${BVID}/`), {
    path: "sidepanel.html",
    enabled: true,
  });
  assert.deepEqual(panelOptions("https://example.com/"), { enabled: false });
});
