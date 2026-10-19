"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const rules = require("../config/competition.json");

assert.strictEqual(rules.rulesVersion, "rsi-poker-4.1");
assert.deepStrictEqual(rules.table, {
  players: 6,
  game: "no-limit-holdem",
  format: "cash",
  smallBlind: 50,
  bigBlind: 100,
  ante: 0,
  startingStack: 10000,
  resetStacksEachHand: true,
});
assert.strictEqual(rules.match.hands, rules.match.rotations * rules.match.handsPerRotation);
assert.deepStrictEqual(rules.match.resetContextBeforeHands, [1, 41, 81, 121, 161, 201]);
assert.strictEqual(rules.match.crossRotationMemory, false);
assert.strictEqual(rules.match.eachParticipantVisitsAllSeats, true);
assert.strictEqual(rules.actions.toIsStreetTotal, true);
assert.deepStrictEqual(rules.limits, {
  actionMs: 200,
  initializationMs: 2000,
  seatCpuMsPerMatch: 20000,
  sourceBytes: 4194304,
  heapBytes: 134217728,
  stackBytes: 1048576,
});
assert.strictEqual(rules.deployment.network, false);
assert.strictEqual(rules.deployment.externalModelFiles, false);

for (const filename of ["submission.js", path.join("neural", "submission_nn.template.js")]) {
  const bytes = fs.statSync(path.join(root, filename)).size;
  assert(bytes <= rules.limits.sourceBytes, `${filename} exceeds source limit`);
}

const checked = spawnSync("python3", [path.join(root, "tools", "competition_rules.py")], {
  cwd: root,
  encoding: "utf8",
});
assert.strictEqual(checked.status, 0, checked.stderr || checked.stdout);
assert.match(checked.stdout, /competition rules: ok \(rsi-poker-4\.1\)/);

console.log("competition constraints test: ok");
