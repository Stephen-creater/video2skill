import test from "node:test";
import assert from "node:assert/strict";

import {
  progressKey,
  reduceProgress,
  isTargetPage,
  normalizeTestResult,
  skillConfig,
  stageEntries,
} from "../src/extension/core.mjs";

const BVID = "BV1ZW42197oE";

test("only the target Bilibili page is supported", () => {
  assert.equal(isTargetPage(`https://www.bilibili.com/video/${BVID}/`), true);
  assert.equal(isTargetPage("https://www.bilibili.com/video/BV0000000000/"), false);
});

test("progress is isolated by target BVID and survives serialized storage", () => {
  assert.equal(progressKey(BVID), `video2skill:${BVID}`);
  const next = reduceProgress({}, { type: "FAIL", step: 2, errorType: "css" });
  assert.deepEqual(JSON.parse(JSON.stringify(next)), {
    currentStep: 2,
    passed: [false, false, false, false],
    errors: { count: 1, types: { css: 1 } },
  });
});

test("test results distinguish pass and fail", () => {
  assert.equal(normalizeTestResult({ tests: [{ status: "pass" }] }).passed, true);
  assert.equal(normalizeTestResult({ tests: [{ status: "fail" }] }).passed, false);
  assert.equal(normalizeTestResult({ results: [{ status: "pass" }] }).passed, true);
  assert.equal(normalizeTestResult({ results: [{ status: "error", errors: ["syntax error"] }] }).errorType, "syntax");
});

test("passing a step advances to the next incomplete step", () => {
  assert.deepEqual(reduceProgress({}, { type: "PASS", step: 0 }), {
    currentStep: 1,
    passed: [true, false, false, false],
    errors: { count: 0, types: {} },
  });
});

test("LiveCodes configuration and backend stages use real API shapes", () => {
  const config = skillConfig({ starter: { html: "<h1>x</h1>", css: "h1{}", js: "" }, tests: [{ code: "expect(true).toBe(true)" }] });
  assert.equal(config.markup.content, "<h1>x</h1>");
  assert.match(config.tests.content, /expect/);
  assert.deepEqual(stageEntries({ stages: { download: { state: "completed" } } }).map((stage) => stage.state), ["completed", "pending", "pending", "pending", "pending"]);
});
