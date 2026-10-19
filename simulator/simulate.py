#!/usr/bin/env python3
"""Dependency-free paired-deal benchmark for six-player policy tuning."""
import argparse
import itertools
import math
import random
import statistics

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = [r+s for r in RANKS for s in SUITS]
POSITIONS = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]

def rv(card): return RANKS.index(card[0]) + 2

def eval5(cards):
    vals = sorted((rv(c) for c in cards), reverse=True)
    counts = {v: vals.count(v) for v in set(vals)}
    groups = sorted(((n, v) for v, n in counts.items()), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    uniq = sorted(set(vals), reverse=True)
    if 14 in uniq: uniq.append(1)
    sh = 0
    for i in range(len(uniq)-4):
        if uniq[i]-uniq[i+4] == 4: sh = max(sh, uniq[i])
    if flush and sh: return (8, sh)
    if groups[0][0] == 4: return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and groups[1][0] == 2: return (6, groups[0][1], groups[1][1])
    if flush: return (5, *vals)
    if sh: return (4, sh)
    if groups[0][0] == 3: return (3, groups[0][1], *(g[1] for g in groups[1:]))
    if groups[0][0] == groups[1][0] == 2: return (2, max(groups[0][1], groups[1][1]), min(groups[0][1], groups[1][1]), groups[2][1])
    if groups[0][0] == 2: return (1, groups[0][1], *(g[1] for g in groups[1:]))
    return (0, *vals)

def evaluate(cards): return max(eval5(c) for c in itertools.combinations(cards, 5))

def strength(hole):
    a,b=rv(hole[0]),rv(hole[1]); hi,lo=max(a,b),min(a,b)
    if a==b: return min(1,.52+(hi-2)*.037)
    x=(hi-2)/12*.46+(lo-2)/12*.20
    if hole[0][1]==hole[1][1]: x+=.075
    gap=hi-lo
    x += .07 if gap==1 else .035 if gap==2 else -.055 if gap>=5 else 0
    if hi==14: x+=.10
    if hi>=12 and lo>=10: x+=.08
    return max(0,min(1,x))

def policy(name, hole, position, facing, rng):
    s=strength(hole)
    if name=="calling": return "call" if s>.20 else "fold"
    if name=="random": return rng.choice(["fold","call","raise"])
    if name=="mixed":
        if s>.78: return "raise"
        if s>.38: return "call"
        return "raise" if rng.random()<.06 else "fold"
    thresholds={"UTG":.64,"HJ":.59,"CO":.53,"BTN":.46,"SB":.50,"BB":.70}
    t=thresholds[position]+(.07 if facing else 0)
    if s>=t+.18: return "raise"
    if s>=t: return "call" if facing else "raise"
    return "fold"

def play_hand(names, deck, button, rng):
    holes=[deck[i*2:i*2+2] for i in range(6)]
    board=deck[12:17]
    invested=[0]*6
    sb=(button+1)%6; bb=(button+2)%6
    invested[sb]=50;invested[bb]=100
    active=set(range(6)); price=100
    order=[(bb+1+i)%6 for i in range(6)]
    raised=False
    for seat in order:
        if len(active) == 1:
            break
        pos=POSITIONS[(seat-button)%6]
        act=policy(names[seat],holes[seat],pos,raised,rng)
        if act=="fold": active.discard(seat)
        elif act=="call": invested[seat]=price
        else:
            price=min(10000,max(230,price*3));invested[seat]=price;raised=True
    if len(active)==1:
        w=next(iter(active));pot=sum(invested);return [pot-invested[i] if i==w else -invested[i] for i in range(6)]
    # Simplified postflop investment model driven by made-hand strength.
    scores={i:evaluate(holes[i]+board) for i in active}
    best=max(scores.values()); winners=[i for i in active if scores[i]==best]
    for street in range(3):
        pot=sum(invested); bet=max(100,int(pot*(.34 if street==0 else .55)))
        for i in list(active):
            if len(active) == 1:
                break
            category=scores[i][0]
            continue_prob=.18+category*.105
            if rng.random()<continue_prob:
                invested[i]=min(10000,invested[i]+bet)
            else:
                active.discard(i)
        if len(active)<=1: break
    if len(active)==1: winners=list(active)
    else:
        best=max(scores[i] for i in active);winners=[i for i in active if scores[i]==best]
    pot=sum(invested); share=pot//len(winners)
    return [(share-invested[i] if i in winners else -invested[i]) for i in range(6)]

def run(hands, seed, candidate, opponents):
    rng=random.Random(seed); totals=[0]*6; per_block=[]
    names=[candidate]+[opponents]*5
    blocks=max(1,hands//240); actual_hands=blocks*240
    for _ in range(blocks):
        deals=[]
        for _hand in range(40):
            deck=DECK[:];rng.shuffle(deck);deals.append(deck)
        block_net=[0]*6
        for rotation in range(6):
            arranged=names[rotation:]+names[:rotation]
            for hand_in_rotation,deck in enumerate(deals):
                result=play_hand(arranged,deck,hand_in_rotation%6,rng)
                unrot=result[-rotation:]+result[:-rotation] if rotation else result
                for i,x in enumerate(unrot): totals[i]+=x;block_net[i]+=x
        per_block.append(block_net[0])
    mbb=10*totals[0]/actual_hands
    return totals,mbb,per_block,actual_hands

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--hands",type=int,default=6000);ap.add_argument("--seed",type=int,default=7607)
    ap.add_argument("--candidate",choices=["tag","mixed","calling","random"],default="tag")
    ap.add_argument("--opponents",choices=["tag","mixed","calling","random"],default="mixed")
    a=ap.parse_args();totals,mbb,blocks,actual=run(a.hands,a.seed,a.candidate,a.opponents)
    print(f"hands={actual} seed={a.seed} candidate={a.candidate} opponents={a.opponents}")
    print(f"candidate_net={totals[0]} candidate_mbb_per_hand={mbb:.3f}")
    if len(blocks)>1:
        mean=statistics.mean(blocks);se=statistics.stdev(blocks)/math.sqrt(len(blocks));print(f"240-hand blocks={len(blocks)} mean_net={mean:.1f} approx95=[{mean-1.96*se:.1f}, {mean+1.96*se:.1f}]")
    print("seat_totals="+",".join(map(str,totals)))

if __name__=="__main__": main()
