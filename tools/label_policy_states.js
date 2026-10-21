#!/usr/bin/env node
"use strict";

/* Deterministically relabel JSONL replay states with an isolated JS policy. */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const readline = require("readline");
const vm = require("vm");
const RULES = require("../config/competition.json");

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}

const root = path.resolve(__dirname, "..");
const options = {
  input: path.resolve(argument("--input", "")),
  policy: path.resolve(argument("--policy", path.join(root, "submission.js"))),
  output: path.resolve(argument("--output", "")),
  report: path.resolve(argument("--report", "")),
  teacherVersion: argument("--teacher-version", "submission-stateless-v1"),
};
for (const name of ["input", "policy", "output", "report"]) {
  if (!options[name]) throw new Error(`missing --${name}`);
}

function sha256File(filename) {
  return crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
}

function stateKey(row) {
  return JSON.stringify([
    row.match_id, row.hand, row.rotation, row.rotation_hand, row.seat, row.street,
    Array.isArray(row.history) ? row.history.length : 0,
    row.pot, row.stack, row.me_bet, row.invested, row.to_call,
  ]);
}

function publicView(row) {
  return {
    rules: RULES.observationRules,
    hand: row.hand,
    rotation: row.rotation,
    rotationHand: row.rotation_hand,
    handsPerRotation: RULES.match.handsPerRotation,
    seat: row.seat,
    player: row.player,
    street: row.street,
    board: row.board,
    button: row.button,
    pot: row.pot,
    level: { sb: RULES.table.smallBlind, bb: RULES.table.bigBlind },
    me: {
      seat: row.seat, player: row.player, cards: row.hole, stack: row.stack,
      bet: row.me_bet, invested: row.invested, position: row.position,
    },
    players: row.players,
    actions: row.history,
    recent: [],
    toCall: row.to_call,
    minRaiseTo: row.min_raise_to,
    maxRaiseTo: row.max_raise_to,
    canRaise: row.can_raise,
    legal: row.legal,
    startingStack: RULES.table.startingStack,
  };
}

function isolatedAction(script, view) {
  const context = vm.createContext({ __AGX_VIEW__: view });
  script.runInContext(context, { timeout: RULES.limits.initializationMs });
  return vm.runInContext("__AGX_POLICY__.act(__AGX_VIEW__)", context, { timeout: RULES.limits.actionMs });
}

function validateAction(view, action) {
  if (!action || typeof action !== "object" || !view.legal.includes(action.type)) {
    throw new Error(`policy returned illegal action type: ${JSON.stringify(action)}`);
  }
  if (action.type === "bet" || action.type === "raise") {
    if (!view.canRaise || !Number.isFinite(action.to) || action.to < view.minRaiseTo || action.to > view.maxRaiseTo) {
      throw new Error(`policy returned illegal raise target: ${JSON.stringify(action)}`);
    }
  }
}

async function main() {
  for (const filename of [options.input, options.policy]) {
    if (!fs.existsSync(filename)) throw new Error(`file does not exist: ${filename}`);
  }
  const policySource = fs.readFileSync(options.policy, "utf8") + "\n;globalThis.__AGX_POLICY__={act:act};\n";
  const script = new vm.Script(policySource, { filename: options.policy });
  fs.mkdirSync(path.dirname(options.output), { recursive: true });
  fs.mkdirSync(path.dirname(options.report), { recursive: true });
  const temporary = `${options.output}.tmp`;
  const output = fs.createWriteStream(temporary, { encoding: "utf8" });
  const input = readline.createInterface({ input: fs.createReadStream(options.input, "utf8"), crlfDelay: Infinity });
  const actions = {};
  let labeled = 0;
  const keys = new Set();
  for await (const line of input) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    const key = stateKey(row);
    if (keys.has(key)) throw new Error(`duplicate difficult-state key: ${key}`);
    keys.add(key);
    const view = publicView(row);
    const action = isolatedAction(script, view);
    validateAction(view, action);
    const originalAction = row.action;
    row.action = action;
    delete row.action_index;
    delete row.action_bucket;
    delete row.action_projection;
    row.dagger_label = {
      version: "agx-policy-state-label.v1",
      teacher: "current-submission-stateless",
      teacher_version: options.teacherVersion,
      state_key: key,
      original_action: originalAction,
    };
    output.write(JSON.stringify(row) + "\n");
    actions[action.type] = (actions[action.type] || 0) + 1;
    labeled++;
  }
  await new Promise((resolve, reject) => output.end((error) => error ? reject(error) : resolve()));
  fs.renameSync(temporary, options.output);
  const report = {
    schema: "agx.policy-state-labels.v1",
    teacher: "current-submission-stateless",
    teacher_version: options.teacherVersion,
    policy: path.relative(root, options.policy),
    policy_sha256: sha256File(options.policy),
    input: path.relative(root, options.input),
    input_sha256: sha256File(options.input),
    labeled,
    action_types: actions,
    isolated_context_per_state: true,
    cross_hand_memory: false,
    output: path.relative(root, options.output),
    output_sha256: sha256File(options.output),
  };
  fs.writeFileSync(options.report, JSON.stringify(report, null, 2) + "\n");
  process.stdout.write(JSON.stringify(report) + "\n");
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
