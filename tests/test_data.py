"""収録データの検証と、全行き先で旅程を組んでも破綻しないかの確認。"""

from collections import Counter
from datetime import date

import pytest

from trip_maker import engine, planner, render
from trip_maker.constants import GENRES, HUBS, NICHE_LABELS
from trip_maker.data import load_destinations
from trip_maker.schema import validate_all

DESTS = load_destinations()


def test_schema():
    assert validate_all(DESTS) == []


def test_coverage():
    """ジャンル・ニッチ度・地域が偏りすぎていないか。"""
    assert len(DESTS) >= 80
    niches = Counter(d["niche"] for d in DESTS)
    assert all(niches[n] >= 5 for n in NICHE_LABELS), niches
    for g in GENRES:
        strong = sum(1 for d in DESTS if d["genres"].get(g, 0) >= 2)
        assert strong >= 5, (g, strong)
    assert sum(d["region"] == "overseas" for d in DESTS) >= 10


def test_day_trip_possible_from_every_hub():
    for hub in HUBS:
        c = engine.Conditions(hub=hub, start_date=date(2026, 10, 14), nights=0, budget_total=10**6)
        assert engine.search(DESTS, c).candidates, hub


def test_access_consistency():
    """同じハブからの所要時間・運賃が極端な値になっていないか（データの桁間違い検出）。"""
    for d in DESTS:
        for hub, options in d["access"].items():
            for o in options:
                if o["mode"] == "flight" and d["region"] != "overseas":
                    assert o["cost"] >= 3000, (d["id"], hub, o)
                if o["hours"] < 1.0:
                    assert o["cost"] <= 3000, (d["id"], hub, o)


CASES = [
    dict(hub="tokyo", nights=0, relation="friends", adults=2, kids=0),
    dict(hub="osaka", nights=1, relation="couple", adults=2, kids=0),
    dict(hub="fukuoka", nights=2, relation="family_kids", adults=2, kids=2),
    dict(hub="sapporo", nights=3, relation="solo", adults=1, kids=0, pace="packed"),
    dict(hub="naha", nights=5, relation="group", adults=6, kids=0, pace="relaxed"),
    dict(hub="sendai", nights=7, relation="family_adults", adults=3, kids=0, multi_stop="on"),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['hub']}-{c['nights']}")
@pytest.mark.parametrize("month", [1, 5, 8, 10])
def test_every_feasible_destination_builds_a_valid_plan(case, month):
    c = engine.Conditions(start_date=date(2026 if month >= 10 else 2027, month, 14), budget_total=10**7,
                          scope="both", **case)
    result = engine.search(DESTS, c)
    assert result.candidates
    for cand in result.candidates:
        plan = planner.make_plan(cand, c, DESTS, 1, 2)
        assert len(plan.days) == c.nights + 1
        assert plan.total == sum(plan.costs.values())
        assert sum(1 for d in plan.days if d.lodging) + sum(
            1 for o in (plan.access_out, plan.access_back) if o.get("overnight")) == c.nights, cand.dest["id"]
        names = [b.title for d in plan.days for b in d.blocks if b.kind == "spot"]
        assert len(names) == len(set(names)), cand.dest["id"]
        for day in plan.days:
            timed = [b for b in day.blocks if b.end > b.start and b.kind != "travel"]
            for a, b in zip(timed, timed[1:]):
                assert a.end <= b.start, (cand.dest["id"], day.number, a.title, b.title)
        render.to_markdown(plan, 5)
