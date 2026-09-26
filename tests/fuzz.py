"""ランダムな条件で大量に旅を作り、旅程の性質（tests/invariants.py）と予算超過率を調べる。

    python -m tests.fuzz 2000 7      # 2000 通り・乱数の種 7
"""

import random
import sys
from collections import Counter
from datetime import date

from tests.invariants import violations
from trip_maker import engine, planner
from trip_maker.constants import GENRES, HUBS
from trip_maker.data import load_destinations


def main(n: int, seed: int) -> None:
    dests = load_destinations()
    rng = random.Random(seed)
    counts: Counter = Counter()
    examples: dict[str, str] = {}
    plans = over = 0
    worst = 0.0
    for i in range(n):
        rel = rng.choice(["solo", "friends", "couple", "family_kids", "family_adults", "group"])
        adults = 1 if rel == "solo" else rng.choice([2, 2, 3, 4, 6])
        kids = rng.choice([1, 2]) if rel == "family_kids" else 0
        c = engine.Conditions(
            hub=rng.choice(list(HUBS)), start_date=date(2026, rng.randint(1, 12), rng.randint(1, 28)),
            nights=rng.choice([0, 1, 1, 2, 2, 3, 4, 5, 6, 7]), adults=adults, kids=kids, relation=rel,
            budget_total=rng.choice([15000, 30000, 50000, 80000, 150000, 300000]) * (adults + kids),
            genres=rng.sample(list(GENRES), rng.choice([0, 1, 2])), niche=rng.randint(1, 5),
            surprise=rng.randint(1, 5), scope=rng.choice(["domestic", "domestic", "both", "overseas"]),
            pace=rng.choice(["relaxed", "normal", "packed"]),
            transport_pref=rng.choice(["auto", "cheap", "fast", "no_flight"]),
            lodging_pref=rng.choice(["auto", "auto", "budget", "standard", "premium"]),
            multi_stop=rng.choice(["auto", "off", "on"]))
        result = engine.search(dests, c)
        if not result.candidates:
            continue
        picked = engine.pick(result.candidates, c.surprise, random.Random(i), k=4)
        plan = planner.make_plan_from_candidates(picked, c, dests, i, i + 1, info=result.info())
        plans += 1
        if plan.over_budget:
            over += 1
            worst = max(worst, plan.total / c.budget_total)
        for v in violations(plan):
            key = v.split(":")[0].split(") ", 1)[-1]
            counts[key] += 1
            examples.setdefault(key, v)
    print(f"plans={plans} over_budget={over} ({over / max(1, plans) * 100:.1f}%) worst={worst:.2f}")
    for key, num in counts.most_common():
        print(f"{num:5d}  {key}  例: {examples[key]}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000, int(sys.argv[2]) if len(sys.argv) > 2 else 7)
