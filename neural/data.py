"""Synthetic poker states, features and conservative oracle labels."""

import out
import math
import multiprocessing as mp
import random

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = [rank + suit for rank in RANKS for suit in SUITS]
BOARD_COUNTS = [0, 3, 4, 5]
INPUT_SIZE = 32
OUTPUT_SIZE = 4
LABELS = ["弃牌/过牌", "跟注/过牌", "小额主动", "大额主动"]


def rank_value(card):
    return RANKS.index(card[0]) + 2


def eval5(cards):
    values = sorted((rank_value(card) for card in cards), reverse=True)
    counts = {value: values.count(value) for value in set(values)}
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    flush = len({card[1] for card in cards}) == 1
    unique = sorted(set(values), reverse=True)
    if 14 in unique:
        unique.append(1)
    straight = 0
    for index in range(len(unique) - 4):
        if unique[index] - unique[index + 4] == 4:
            straight = max(straight, unique[index])
    if flush and straight:
        return 8, straight
    if groups[0][0] == 4:
        return 7, groups[0][1], groups[1][1]
    if groups[0][0] == 3 and groups[1][0] == 2:
        return 6, groups[0][1], groups[1][1]
    if flush:
        return (5, *values)
    if straight:
        return 4, straight
    if groups[0][0] == 3:
        return (3, groups[0][1], *(group[1] for group in groups[1:]))
    if groups[0][0] == groups[1][0] == 2:
        return 2, max(groups[0][1], groups[1][1]), min(groups[0][1], groups[1][1]), groups[2][1]
    if groups[0][0] == 2:
        return (1, groups[0][1], *(group[1] for group in groups[1:]))
    return (0, *values)


def evaluate(cards):
    if len(cards) < 5:
        return (0,)
    best = None
    length = len(cards)
    for a in range(length - 4):
        for b in range(a + 1, length - 3):
            for c in range(b + 1, length - 2):
                for d in range(c + 1, length - 1):
                    for e in range(d + 1, length):
                        score = eval5([cards[a], cards[b], cards[c], cards[d], cards[e]])
                        if best is None or score > best:
                            best = score
    return best


def preflop_strength(cards):
    a, b = rank_value(cards[0]), rank_value(cards[1])
    high, low = max(a, b), min(a, b)
    if a == b:
        return min(1.0, 0.52 + (high - 2) * 0.037)
    score = (high - 2) / 12 * 0.46 + (low - 2) / 12 * 0.20
    if cards[0][1] == cards[1][1]:
        score += 0.075
    gap = high - low
    score += 0.07 if gap == 1 else 0.035 if gap == 2 else -0.055 if gap >= 5 else 0
    if high == 14:
        score += 0.10
    if high >= 12 and low >= 10:
        score += 0.08
    return max(0.0, min(1.0, score))


def texture(board, hole):
    suits, ranks, values = {}, {}, []
    for card in board + hole:
        suits[card[1]] = suits.get(card[1], 0) + 1
        value = rank_value(card)
        ranks[value] = ranks.get(value, 0) + 1
        values.append(value)
    unique = sorted(set(values))
    connected = sum(1 for index in range(1, len(unique)) if unique[index] - unique[index - 1] <= 2)
    max_suit = max(suits.values(), default=0)
    return {
        "flush_draw": max_suit >= 4,
        "wet": max_suit >= 3 or connected >= 3,
        "paired": any(count >= 2 for count in ranks.values()),
    }


def state_features(state):
    street, position = state["street"], state["position"]
    hole, board = state["hole"], state["board"]
    high = max(rank_value(hole[0]), rank_value(hole[1]))
    low = min(rank_value(hole[0]), rank_value(hole[1]))
    info = texture(board, hole)
    category = evaluate(hole + board)[0] if len(board) >= 3 else 0
    pot_odds = state["to_call"] / max(1, state["pot"] + state["to_call"])
    spr = state["stack"] / max(1, state["pot"])
    features = [1.0 if street == index else 0.0 for index in range(4)]
    features.extend(1.0 if position == index else 0.0 for index in range(6))
    features.extend([
        high / 14,
        low / 14,
        float(high == low),
        float(hole[0][1] == hole[1][1]),
        (high - low) / 12,
        category / 8,
        float(info["flush_draw"]),
        float(info["wet"]),
        float(info["paired"]),
        min(1.0, state["pot"] / 20000),
        min(1.0, state["to_call"] / 10000),
        min(1.0, state["stack"] / 10000),
        pot_odds,
        min(1.0, spr / 10),
        state["opponents"] / 5,
        min(1.0, state["preflop_raises"] / 4),
        min(1.0, state["street_raises"] / 4),
        min(1.0, state["callers"] / 5),
        float(state["can_raise"]),
        float(state["to_call"] == 0),
        min(1.0, state["invested"] / 10000),
        max((rank_value(card) for card in board), default=0) / 14,
    ])
    if len(features) != INPUT_SIZE:
        raise AssertionError(f"feature count {len(features)} != {INPUT_SIZE}")
    return features, info


def sample_opponent(deck, floor, rng):
    best, best_strength = None, -1
    for _ in range(5):
        cards = rng.sample(deck, 2)
        strength = preflop_strength(cards)
        if strength > best_strength:
            best, best_strength = cards, strength
        if strength >= floor:
            best = cards
            break
    deck.remove(best[0])
    deck.remove(best[1])
    return best


def estimate_equity(state, trials, rng):
    known = state["hole"] + state["board"]
    base = [card for card in DECK if card not in known]
    needed = 5 - len(state["board"])
    floor = min(0.72, 0.10 + state["preflop_raises"] * 0.16 + state["street_raises"] * 0.08)
    result = 0.0
    for _ in range(trials):
        deck = base[:]
        rng.shuffle(deck)
        board = state["board"] + [deck.pop() for _ in range(needed)]
        hero = evaluate(state["hole"] + board)
        tied, beaten = 1, False
        for _opponent in range(state["opponents"]):
            score = evaluate(sample_opponent(deck, floor, rng) + board)
            if score > hero:
                beaten = True
                break
            if score == hero:
                tied += 1
        if not beaten:
            result += 1 / tied
    return result / trials


def oracle_label(state, equity, info):
    value = max(0.0, min(1.0, equity - (state["opponents"] - 1) * 0.015))
    pot_odds = state["to_call"] / max(1, state["pot"] + state["to_call"])
    call_ev = value * (state["pot"] + state["to_call"]) - state["to_call"]
    spr = state["stack"] / max(1, state["pot"])
    if state["to_call"] == 0:
        if state["can_raise"] and (value > 0.86 or (spr < 0.85 and value > 0.76)):
            return 3
        if state["can_raise"] and value >= (0.68 if info["wet"] else 0.63):
            return 2
        return 1
    if state["can_raise"] and value > 0.84:
        return 3
    if state["can_raise"] and value > 0.74 and call_ev > state["pot"] * 0.10:
        return 2
    if call_ev >= 0 and value >= pot_odds + 0.035:
        return 1
    return 0


def random_state(rng):
    deck = DECK[:]
    rng.shuffle(deck)
    hole = [deck.pop(), deck.pop()]
    street = rng.choices([0, 1, 2, 3], weights=[0.18, 0.38, 0.24, 0.20])[0]
    board = [deck.pop() for _ in range(BOARD_COUNTS[street])]
    opponents = rng.randint(1, 5)
    pot = int(round(math.exp(rng.uniform(math.log(150), math.log(14000)))))
    stack = rng.randint(300, 10000)
    facing = rng.random() < (0.20 if street == 0 else 0.52)
    to_call = min(stack, max(50, int(pot * rng.uniform(0.18, 1.05)))) if facing else 0
    preflop_raises = rng.choices([0, 1, 2, 3], weights=[0.46, 0.39, 0.12, 0.03])[0]
    street_raises = 0 if street == 0 else rng.choices([0, 1, 2], weights=[0.64, 0.31, 0.05])[0]
    return {
        "street": street,
        "position": rng.randrange(6),
        "hole": hole,
        "board": board,
        "pot": pot,
        "to_call": to_call,
        "stack": stack,
        "invested": rng.randint(0, min(10000 - stack, pot)),
        "opponents": opponents,
        "preflop_raises": preflop_raises,
        "street_raises": street_raises,
        "callers": rng.randint(0, min(5, opponents)),
        "can_raise": stack > to_call + 100 and rng.random() > 0.08,
    }


def generate_chunk(task):
    start_seed, count, mc_samples = task
    examples = []
    for offset in range(count):
        rng = random.Random(start_seed + offset * 104729)
        state = random_state(rng)
        features, info = state_features(state)
        equity = estimate_equity(state, mc_samples, rng)
        examples.append((features, oracle_label(state, equity, info)))
    return examples


def generate_dataset(samples, seed, mc_samples, workers):
    chunk_size = 128
    tasks = []
    for chunk, start in enumerate(range(0, samples, chunk_size)):
        tasks.append((seed + chunk * 1000003, min(chunk_size, samples - start), mc_samples))
    data = []
    if workers == 1:
        iterator = map(generate_chunk, tasks)
    else:
        pool = mp.Pool(processes=workers)
        iterator = pool.imap(generate_chunk, tasks)
    try:
        for index, examples in enumerate(iterator, 1):
            data.extend(examples)
            if index % max(1, len(tasks) // 20) == 0 or index == len(tasks):
                print(f"生成数据：{len(data)}/{samples}", flush=True)
    finally:
        if workers != 1:
            pool.close()
            pool.join()
    return data


def save_dataset(filename, data):
    filename.parent.mkdir(parents=True, exist_ok=True)
    with filename.open("w", encoding="utf-8") as handle:
        for features, label in data:
            handle.write(out.dumps({"x": features, "y": label}, separators=(",", ":")) + "\n")


def load_dataset(filename):
    data = []
    with filename.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = out.loads(line)
            data.append((row["x"], int(row["y"])))
    return data
