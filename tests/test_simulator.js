"use strict";

const assert = require("assert");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const result = spawnSync(process.execPath, [
  path.join(root, "simulator", "simulate_submission.js"),
  "--matches", "1",
  "--seed", "99173",
], {
  cwd: root,
  encoding: "utf8",
  timeout: 30000,
});

assert.strictEqual(result.status, 0, result.stderr || result.stdout);
assert.match(result.stdout, /完整比赛：1/);
assert.match(result.stdout, /非法\/异常：0；超预算：0/);
assert.match(result.stdout, /mbb\/手：-?\d+\.\d{3}/);
assert.match(result.stdout, /第一名份额：\d+\.\d{2}%/);

console.log("direct submission simulator test: ok");
