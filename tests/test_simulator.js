"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const jsonOut = path.join(os.tmpdir(), `agx-simulator-${process.pid}.json`);
const result = spawnSync(process.execPath, [
  path.join(root, "simulator", "simulate_submission.js"),
  "--matches", "1",
  "--seed", "99173",
  "--json-out", jsonOut,
], {
  cwd: root,
  encoding: "utf8",
  timeout: 30000,
});

assert.strictEqual(result.status, 0, result.stderr || result.stdout);
assert.match(result.stdout, /完整比赛：1/);
assert.match(result.stdout, /规则：rsi-poker-4\.1；6人；50\/100；100BB；6×40手/);
assert.match(result.stdout, /非法\/异常：0；超预算：0；整局CPU超限：0/);
assert.match(result.stdout, /候选上下文初始化：6（每局6次）/);
assert.match(result.stdout, /mbb\/手：-?\d+\.\d{3}/);
assert.match(result.stdout, /第一名份额：\d+\.\d{2}%/);
const summary = JSON.parse(fs.readFileSync(jsonOut, "utf8"));
assert.strictEqual(summary.schema, "agx.paired-policy-evaluation.v1");
assert.strictEqual(summary.hands, 240);
assert.strictEqual(summary.match_nets.length, 1);
assert.strictEqual(summary.invalid_actions, 0);
assert.deepStrictEqual(summary.invalid_action_reasons, {});
assert.deepStrictEqual(summary.noregrets_streets, []);
assert.strictEqual(summary.javascript_candidate, null);
fs.unlinkSync(jsonOut);

const rulesProbe = spawnSync(process.execPath, [
  path.join(root, "simulator", "simulate_submission.js"),
  "--matches", "1",
  "--seed", "99173",
  "--candidate", path.join(root, "tests", "fixtures", "rules_probe_submission.js"),
], {
  cwd: root,
  encoding: "utf8",
  timeout: 30000,
});
assert.strictEqual(rulesProbe.status, 0, rulesProbe.stderr || rulesProbe.stdout);
assert.match(rulesProbe.stdout, /非法\/异常：0；超预算：0；整局CPU超限：0/);

const slow = spawnSync(process.execPath, [
  path.join(root, "simulator", "simulate_submission.js"),
  "--matches", "1",
  "--seed", "99173",
  "--budget-ms", "5",
  "--candidate", path.join(root, "tests", "fixtures", "slow_submission.js"),
], {
  cwd: root,
  encoding: "utf8",
  timeout: 30000,
});
assert.strictEqual(slow.status, 0, slow.stderr || slow.stdout);
assert.match(slow.stdout, /超预算：[1-9]\d*/);

console.log("direct submission simulator test: ok");
