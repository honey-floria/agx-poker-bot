"use strict";

/*
 * Direct benchmark for AGX-style submission.js policies.
 * Uses only Node.js built-ins and gives every fixed participant an isolated VM.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const RULES = require("../config/competition.json");

const START = RULES.table.startingStack;
const SB = RULES.table.smallBlind;
const BB = RULES.table.bigBlind;
const HANDS_PER_ROTATION = RULES.match.handsPerRotation;
const ROTATIONS = RULES.match.rotations;
const HANDS_PER_MATCH = HANDS_PER_ROTATION * ROTATIONS;
const ACTION_BUDGET_MS = RULES.limits.actionMs;
const INITIALIZATION_BUDGET_MS = RULES.limits.initializationMs;
const SEAT_CPU_BUDGET_MS = RULES.limits.seatCpuMsPerMatch;
const RANKS = "23456789TJQKA";
const SUITS = "cdhs";
const STREETS = ["preflop", "flop", "turn", "river"];
const BOARD_COUNTS = [0, 3, 4, 5];
const POSITIONS = ["BTN", "SB", "BB", "UTG", "HJ", "CO"];

function argument(name, fallback) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

const root = path.resolve(__dirname, "..");
const options = {
  matches: Math.max(1, Number(argument("--matches", "10")) || 10),
  seed: Number(argument("--seed", "7607")) || 7607,
  budgetMs: Math.min(ACTION_BUDGET_MS, Math.max(1, Math.floor(Number(argument("--budget-ms", String(ACTION_BUDGET_MS)))) || ACTION_BUDGET_MS)),
  candidate: path.resolve(process.cwd(), argument("--candidate", path.join(root, "submission.js"))),
  opponent: path.resolve(process.cwd(), argument("--opponent", path.join(root, "baselines/submission_v1.js"))),
};

function mulberry32(seed) {
  let value = seed >>> 0;
  return function random() {
    value = (value + 0x6D2B79F5) >>> 0;
    let t = value;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffledDeck(random) {
  const deck = [...RANKS].flatMap((rank) => [...SUITS].map((suit) => rank + suit));
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}

function loadPolicy(filename, seed) {
  const started = process.hrtime.bigint();
  const cpuStarted = process.cpuUsage();
  const source = fs.readFileSync(filename, "utf8");
  const math = Object.create(Math);
  math.random = mulberry32(seed);
  const sandbox = { Math: math };
  vm.createContext(sandbox);
  vm.runInContext(source + "\nthis.__agxAct = act;", sandbox, {
    filename,
    timeout: INITIALIZATION_BUDGET_MS,
  });
  if (typeof sandbox.__agxAct !== "function") throw new Error(`${filename} 没有提供 act(view)`);
  const initializationMs = Number(process.hrtime.bigint() - started) / 1e6;
  const initializationCpu = process.cpuUsage(cpuStarted);
  const initializationCpuMs = (initializationCpu.user + initializationCpu.system) / 1000;
  if (initializationMs > INITIALIZATION_BUDGET_MS) {
    throw new Error(`${filename} 初始化耗时 ${initializationMs.toFixed(3)}ms，超过 ${INITIALIZATION_BUDGET_MS}ms`);
  }
  return {
    initializationMs,
    initializationCpuMs,
    act(view, timeoutMs) {
      sandbox.__agxView = view;
      return vm.runInContext("__agxAct(__agxView)", sandbox, { timeout: timeoutMs });
    },
  };
}

function rankValue(card) {
  return RANKS.indexOf(card[0]) + 2;
}

function evaluate5(cards) {
  const values = cards.map(rankValue).sort((a, b) => b - a);
  const counts = {};
  for (const value of values) counts[value] = (counts[value] || 0) + 1;
  const groups = Object.entries(counts)
    .map(([rank, count]) => [count, Number(rank)])
    .sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  const flush = new Set(cards.map((card) => card[1])).size === 1;
  const unique = [...new Set(values)];
  if (unique.includes(14)) unique.push(1);
  let straightHigh = 0;
  for (let i = 0; i <= unique.length - 5; i++) {
    if (unique[i] - unique[i + 4] === 4) straightHigh = Math.max(straightHigh, unique[i]);
  }
  if (flush && straightHigh) return [8, straightHigh];
  if (groups[0][0] === 4) return [7, groups[0][1], groups[1][1]];
  if (groups[0][0] === 3 && groups[1][0] === 2) return [6, groups[0][1], groups[1][1]];
  if (flush) return [5, ...values];
  if (straightHigh) return [4, straightHigh];
  if (groups[0][0] === 3) return [3, groups[0][1], ...groups.slice(1).map((group) => group[1])];
  if (groups[0][0] === 2 && groups[1][0] === 2) {
    return [2, Math.max(groups[0][1], groups[1][1]), Math.min(groups[0][1], groups[1][1]), groups[2][1]];
  }
  if (groups[0][0] === 2) return [1, groups[0][1], ...groups.slice(1).map((group) => group[1])];
  return [0, ...values];
}

function compareScore(left, right) {
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const a = left[i] || 0;
    const b = right[i] || 0;
    if (a !== b) return a - b;
  }
  return 0;
}

function evaluate(cards) {
  let best = null;
  for (let a = 0; a < cards.length - 4; a++) {
    for (let b = a + 1; b < cards.length - 3; b++) {
      for (let c = b + 1; c < cards.length - 2; c++) {
        for (let d = c + 1; d < cards.length - 1; d++) {
          for (let e = d + 1; e < cards.length; e++) {
            const score = evaluate5([cards[a], cards[b], cards[c], cards[d], cards[e]]);
            if (!best || compareScore(score, best) > 0) best = score;
          }
        }
      }
    }
  }
  return best;
}

function positionFor(seat, button) {
  return POSITIONS[(seat - button + 6) % 6];
}

function pot(game) {
  return game.players.reduce((sum, player) => sum + player.invested, 0);
}

function currentBet(game) {
  return Math.max(...game.players.map((player) => player.bet));
}

function activePlayers(game) {
  return game.players.filter((player) => !player.folded);
}

function canAct(player) {
  return !player.folded && !player.allin && player.stack > 0;
}

function roundComplete(game) {
  const highest = currentBet(game);
  return game.players.every((player) => !canAct(player) || (player.acted && player.bet === highest));
}

function commitChips(player, amount) {
  const paid = Math.max(0, Math.min(player.stack, Math.floor(amount)));
  player.stack -= paid;
  player.bet += paid;
  player.invested += paid;
  if (player.stack === 0) player.allin = true;
  return paid;
}

function postBlind(game, seat, amount) {
  commitChips(game.players[seat], amount);
}

function legalState(game, seat) {
  const player = game.players[seat];
  const highest = currentBet(game);
  const toCall = Math.max(0, highest - player.bet);
  const maxRaiseTo = player.bet + player.stack;
  const minRaiseTo = highest + game.lastRaise;
  const canRaise = maxRaiseTo >= minRaiseTo;
  const legal = [];
  if (toCall === 0) legal.push("check");
  else legal.push("fold", "call");
  if (canRaise) legal.push(highest === 0 ? "bet" : "raise");
  if (player.stack > 0) legal.push("allin");
  return { toCall, minRaiseTo, maxRaiseTo, canRaise, legal };
}

function publicView(game, seat) {
  const player = game.players[seat];
  const legal = legalState(game, seat);
  return {
    rules: RULES.rulesVersion,
    hand: game.globalHand,
    rotation: game.rotation,
    rotationHand: game.rotationHand + 1,
    handsPerRotation: HANDS_PER_ROTATION,
    seat,
    player: player.id,
    street: STREETS[game.street],
    board: game.board.slice(0, BOARD_COUNTS[game.street]),
    button: game.button,
    pot: pot(game),
    level: { sb: SB, bb: BB },
    me: {
      seat,
      player: player.id,
      cards: player.hole.slice(),
      stack: player.stack,
      bet: player.bet,
      invested: player.invested,
      position: positionFor(seat, game.button),
    },
    players: game.players.map((item) => ({
      seat: item.seat,
      player: item.id,
      stack: item.stack,
      bet: item.bet,
      invested: item.invested,
      state: item.folded ? "folded" : (item.allin ? "allin" : "in"),
      position: positionFor(item.seat, game.button),
    })),
    actions: game.actions.slice(),
    recent: [],
    toCall: legal.toCall,
    minRaiseTo: legal.minRaiseTo,
    maxRaiseTo: legal.maxRaiseTo,
    canRaise: legal.canRaise,
    legal: legal.legal,
    startingStack: START,
  };
}

function recordAction(game, player, type, extra) {
  game.actions.push(Object.assign({
    player: player.id,
    seat: player.seat,
    street: STREETS[game.street],
    type,
  }, extra || {}));
}

function fallbackAction(view) {
  if (view.toCall === 0 && view.legal.includes("check")) return { type: "check" };
  if (view.legal.includes("fold")) return { type: "fold" };
  return { type: view.legal[0] };
}

function applyAction(game, seat, rawAction) {
  const player = game.players[seat];
  const state = legalState(game, seat);
  let action = rawAction && typeof rawAction === "object" ? rawAction : fallbackAction(publicView(game, seat));
  if (!state.legal.includes(action.type)) action = fallbackAction(publicView(game, seat));
  const highest = currentBet(game);

  if (action.type === "fold") {
    player.folded = true;
    player.acted = true;
    recordAction(game, player, "fold");
    return;
  }
  if (action.type === "check") {
    player.acted = true;
    recordAction(game, player, "check");
    return;
  }
  if (action.type === "call") {
    const paid = commitChips(player, state.toCall);
    player.acted = true;
    recordAction(game, player, "call", { amount: paid, to: player.bet });
    return;
  }

  let target = action.type === "allin" ? state.maxRaiseTo : Math.floor(Number(action.to));
  if (!Number.isFinite(target)) target = state.minRaiseTo;
  target = Math.min(state.maxRaiseTo, Math.max(player.bet, target));
  if (target <= highest) {
    const paid = commitChips(player, state.toCall);
    player.acted = true;
    recordAction(game, player, state.toCall ? "call" : "check", { amount: paid, to: player.bet });
    return;
  }

  const oldHighest = highest;
  const paid = commitChips(player, target - player.bet);
  const raiseSize = player.bet - oldHighest;
  const fullRaise = raiseSize >= game.lastRaise;
  player.acted = true;
  if (fullRaise) {
    game.lastRaise = raiseSize;
    for (const other of game.players) {
      if (other.seat !== seat && canAct(other)) other.acted = false;
    }
  }
  recordAction(game, player, oldHighest === 0 ? "bet" : "raise", {
    amount: paid,
    to: player.bet,
    allin: player.allin,
  });
}

function nextActor(game, fromSeat) {
  for (let offset = 0; offset < 6; offset++) {
    const seat = (fromSeat + offset) % 6;
    if (canAct(game.players[seat])) return seat;
  }
  return -1;
}

function runBettingRound(game, bots, metrics, startSeat, budgetMs) {
  let cursor = startSeat;
  let actions = 0;
  while (!roundComplete(game) && activePlayers(game).length > 1) {
    if (++actions > 200) throw new Error("单手动作数超过200，可能存在状态机循环");
    const seat = nextActor(game, cursor);
    if (seat < 0) break;
    const view = publicView(game, seat);
    const participant = game.players[seat].id;
    let action;
    let failed = false;
    let hardTimeout = false;
    if (metrics.cpuMs[participant] >= SEAT_CPU_BUDGET_MS) {
      metrics.cpuExceeded[participant]++;
      action = fallbackAction(view);
      metrics.actionTypes[participant][action.type] = (metrics.actionTypes[participant][action.type] || 0) + 1;
      applyAction(game, seat, action);
      cursor = (seat + 1) % 6;
      continue;
    }
    const started = process.hrtime.bigint();
    const cpuStarted = process.cpuUsage();
    try {
      action = bots[participant].act(view, budgetMs);
    } catch (error) {
      failed = true;
      hardTimeout = Boolean(error && error.code === "ERR_SCRIPT_EXECUTION_TIMEOUT");
      action = fallbackAction(view);
    }
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
    const cpuUsed = process.cpuUsage(cpuStarted);
    const cpuMs = (cpuUsed.user + cpuUsed.system) / 1000;
    metrics.latencies[participant].push(elapsedMs);
    metrics.cpuMs[participant] += cpuMs;
    if (failed || !action || typeof action !== "object" || !view.legal.includes(action.type)) {
      metrics.invalid[participant]++;
      action = fallbackAction(view);
    }
    if (hardTimeout || elapsedMs > budgetMs || metrics.cpuMs[participant] > SEAT_CPU_BUDGET_MS) {
      metrics.timeouts[participant]++;
      if (metrics.cpuMs[participant] > SEAT_CPU_BUDGET_MS) metrics.cpuExceeded[participant]++;
      action = fallbackAction(view);
    }
    metrics.actionTypes[participant][action.type] = (metrics.actionTypes[participant][action.type] || 0) + 1;
    applyAction(game, seat, action);
    cursor = (seat + 1) % 6;
  }
}

function sidePots(players) {
  const levels = [...new Set(players.filter((player) => player.invested > 0).map((player) => player.invested))].sort((a, b) => a - b);
  let previous = 0;
  const pots = [];
  for (const level of levels) {
    const contributors = players.filter((player) => player.invested >= level);
    const amount = (level - previous) * contributors.length;
    const eligible = contributors.filter((player) => !player.folded);
    if (amount > 0 && eligible.length) pots.push({ amount, eligible });
    previous = level;
  }
  return pots;
}

function settle(game) {
  const active = activePlayers(game);
  if (active.length === 1) {
    active[0].stack += pot(game);
  } else {
    const awards = new Map();
    for (const sidePot of sidePots(game.players)) {
      let best = null;
      let winners = [];
      for (const player of sidePot.eligible) {
        const score = evaluate(player.hole.concat(game.board));
        if (!best || compareScore(score, best) > 0) {
          best = score;
          winners = [player];
        } else if (compareScore(score, best) === 0) {
          winners.push(player);
        }
      }
      winners.sort((a, b) => ((a.seat - game.button + 5) % 6) - ((b.seat - game.button + 5) % 6));
      const share = Math.floor(sidePot.amount / winners.length);
      let remainder = sidePot.amount - share * winners.length;
      for (const winner of winners) {
        awards.set(winner, (awards.get(winner) || 0) + share + (remainder-- > 0 ? 1 : 0));
      }
    }
    for (const [player, amount] of awards.entries()) player.stack += amount;
  }

  const net = Array(6).fill(0);
  for (const player of game.players) net[player.id] = player.stack - START;
  const zeroSum = net.reduce((sum, value) => sum + value, 0);
  if (zeroSum !== 0) throw new Error(`单手净额不守恒：${zeroSum}`);
  return net;
}

function playHand({ deck, button, rotation, rotationHand, bots, metrics, budgetMs }) {
  const players = Array.from({ length: 6 }, (_, seat) => {
    const id = (seat + rotation) % 6;
    return {
      id,
      seat,
      hole: deck.slice(seat * 2, seat * 2 + 2),
      stack: START,
      bet: 0,
      invested: 0,
      folded: false,
      allin: false,
      acted: false,
    };
  });
  const game = {
    players,
    board: deck.slice(12, 17),
    button,
    rotation,
    rotationHand,
    globalHand: rotation * HANDS_PER_ROTATION + rotationHand + 1,
    street: 0,
    actions: [],
    lastRaise: BB,
  };

  postBlind(game, (button + 1) % 6, SB);
  postBlind(game, (button + 2) % 6, BB);

  for (let street = 0; street < 4 && activePlayers(game).length > 1; street++) {
    game.street = street;
    if (street > 0) {
      for (const player of game.players) {
        player.bet = 0;
        player.acted = false;
      }
      game.lastRaise = BB;
    }
    const startSeat = street === 0 ? (button + 3) % 6 : (button + 1) % 6;
    runBettingRound(game, bots, metrics, startSeat, budgetMs);
  }
  return settle(game);
}

function percentile(values, fraction) {
  if (!values.length) return 0;
  const sorted = values.slice().sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))];
}

function runMatch(matchIndex, deals, buttons) {
  const metrics = {
    latencies: Array.from({ length: 6 }, () => []),
    invalid: Array(6).fill(0),
    timeouts: Array(6).fill(0),
    cpuMs: Array(6).fill(0),
    cpuExceeded: Array(6).fill(0),
    initializationMs: Array.from({ length: 6 }, () => []),
    contextInitializations: Array(6).fill(0),
    actionTypes: Array.from({ length: 6 }, () => ({})),
  };
  const totals = Array(6).fill(0);
  for (let rotation = 0; rotation < ROTATIONS; rotation++) {
    // The platform destroys policy state at every 40-hand boundary. Reloading all
    // policies here prevents accidental cross-rotation opponent statistics.
    const bots = Array.from({ length: 6 }, (_, id) => {
      const policy = loadPolicy(
        id === 0 ? options.candidate : options.opponent,
        options.seed + matchIndex * 1009 + rotation * 193 + id * 97
      );
      metrics.initializationMs[id].push(policy.initializationMs);
      metrics.cpuMs[id] += policy.initializationCpuMs;
      metrics.contextInitializations[id]++;
      return policy;
    });
    for (let hand = 0; hand < HANDS_PER_ROTATION; hand++) {
      const net = playHand({
        deck: deals[hand],
        button: buttons[hand],
        rotation,
        rotationHand: hand,
        bots,
        metrics,
        budgetMs: options.budgetMs,
      });
      for (let id = 0; id < 6; id++) totals[id] += net[id];
    }
  }
  if (totals.reduce((sum, value) => sum + value, 0) !== 0) throw new Error("完整比赛净额不守恒");
  return { totals, metrics };
}

function main() {
  for (const filename of [options.candidate, options.opponent]) {
    if (!fs.existsSync(filename)) throw new Error(`文件不存在：${filename}`);
  }
  const random = mulberry32(options.seed);
  let candidateNet = 0;
  let winShare = 0;
  let outrightWins = 0;
  const matchNets = [];
  const candidateLatencies = [];
  let invalid = 0;
  let timeouts = 0;
  let cpuExceeded = 0;
  let candidateCpuMs = 0;
  const initializationLatencies = [];
  let contextInitializations = 0;
  const actionTypes = {};

  for (let match = 0; match < options.matches; match++) {
    const deals = Array.from({ length: HANDS_PER_ROTATION }, () => shuffledDeck(random));
    const offset = Math.floor(random() * 6);
    const buttons = Array.from({ length: HANDS_PER_ROTATION }, (_, hand) => (hand + offset) % 6);
    const result = runMatch(match, deals, buttons);
    const net = result.totals[0];
    const best = Math.max(...result.totals);
    const tiedFirst = result.totals.filter((value) => value === best).length;
    candidateNet += net;
    matchNets.push(net);
    if (net === best) {
      winShare += 1 / tiedFirst;
      if (tiedFirst === 1) outrightWins++;
    }
    candidateLatencies.push(...result.metrics.latencies[0]);
    invalid += result.metrics.invalid[0];
    timeouts += result.metrics.timeouts[0];
    cpuExceeded += result.metrics.cpuExceeded[0];
    candidateCpuMs += result.metrics.cpuMs[0];
    initializationLatencies.push(...result.metrics.initializationMs[0]);
    contextInitializations += result.metrics.contextInitializations[0];
    for (const [type, count] of Object.entries(result.metrics.actionTypes[0])) actionTypes[type] = (actionTypes[type] || 0) + count;
    process.stdout.write(`比赛 ${match + 1}/${options.matches}：候选净额 ${net >= 0 ? "+" : ""}${net}，名次 ${1 + result.totals.filter((value) => value > net).length}\n`);
  }

  const hands = options.matches * HANDS_PER_MATCH;
  const mean = candidateNet / options.matches;
  const variance = matchNets.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / Math.max(1, matchNets.length - 1);
  const standardError = Math.sqrt(variance / options.matches);
  console.log("\n=== 汇总 ===");
  console.log(`规则：${RULES.rulesVersion}；${RULES.table.players}人；${SB}/${BB}；${START / BB}BB；${ROTATIONS}×${HANDS_PER_ROTATION}手`);
  console.log(`候选：${options.candidate}`);
  console.log(`对手：${options.opponent}`);
  console.log(`完整比赛：${options.matches}；候选手数：${hands}`);
  console.log(`累计净额：${candidateNet >= 0 ? "+" : ""}${candidateNet}`);
  console.log(`平均每局净额：${mean.toFixed(2)}；近似95%区间：[ ${(mean - 1.96 * standardError).toFixed(2)}, ${(mean + 1.96 * standardError).toFixed(2)} ]`);
  console.log(`mbb/手：${(10 * candidateNet / hands).toFixed(3)}`);
  console.log(`第一名份额：${(100 * winShare / options.matches).toFixed(2)}%；单独第一：${outrightWins}/${options.matches}`);
  console.log(`候选动作数：${candidateLatencies.length}；非法/异常：${invalid}；超预算：${timeouts}；整局CPU超限：${cpuExceeded}`);
  console.log(`候选上下文初始化：${contextInitializations}（每局${ROTATIONS}次）；初始化最大耗时：${Math.max(0, ...initializationLatencies).toFixed(3)}ms`);
  console.log(`候选累计CPU：${candidateCpuMs.toFixed(3)}ms；每局上限：${SEAT_CPU_BUDGET_MS}ms`);
  console.log(`候选动作分布：${Object.entries(actionTypes).map(([type, count]) => `${type}=${count}`).join("，")}`);
  const averageLatency = candidateLatencies.reduce((sum, value) => sum + value, 0) / Math.max(1, candidateLatencies.length);
  console.log(`耗时ms 平均/P50/P95/P99/最大：${averageLatency.toFixed(3)} / ${percentile(candidateLatencies, 0.50).toFixed(3)} / ${percentile(candidateLatencies, 0.95).toFixed(3)} / ${percentile(candidateLatencies, 0.99).toFixed(3)} / ${Math.max(0, ...candidateLatencies).toFixed(3)}`);
}

main();
