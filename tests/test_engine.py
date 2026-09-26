import copy
import random
from datetime import date

import pytest

from tests.fixtures import ONOMICHI, all_fixtures, make_far_flight_only, make_island, make_winter_closed
from trip_maker import engine
from trip_maker.engine import Conditions
from trip_maker.schema import validate_destination


def cond(**kw) -> Conditions:
    base = dict(hub="osaka", start_date=date(2026, 10, 14), nights=1, adults=2, kids=0, relation="couple",
                budget_total=200000, genres=[], niche=3, surprise=2)
    base.update(kw)
    return Conditions(**base)


def ids(result: engine.Search) -> set[str]:
    return {c.dest["id"] for c in result.candidates}


# ── スキーマ ──────────────────────────────────────────────────────
def test_fixture_is_valid():
    assert validate_destination(ONOMICHI) == []


def test_schema_rejects_missing_hub():
    d = copy.deepcopy(ONOMICHI)
    del d["access"]["naha"]
    assert any("naha" in e for e in validate_destination(d))


def test_schema_rejects_unordered_lodging_prices():
    d = copy.deepcopy(ONOMICHI)
    d["lodging"]["budget"]["price"] = 99999
    assert any("budget ≤ standard ≤ premium" in e for e in validate_destination(d))


# ── 絞り込み ──────────────────────────────────────────────────────
def test_day_trip_excludes_far_destinations():
    result = engine.search(all_fixtures(), cond(nights=0))
    assert "onomichi_shimanami" in ids(result)
    assert "test_far" not in ids(result)
    assert "test_island" not in ids(result)


def test_avoid_months_excludes_destination():
    winter = engine.search([make_winter_closed()], cond(start_date=date(2027, 1, 10)))
    summer = engine.search([make_winter_closed()], cond(start_date=date(2026, 8, 20)))
    assert not winter.candidates
    assert summer.candidates


def test_trip_spanning_into_avoid_month_is_excluded():
    # 11/29 出発の 3 泊 → 12 月にかかる
    result = engine.search([make_winter_closed()], cond(start_date=date(2026, 11, 29), nights=3))
    assert not result.candidates


def test_overnight_ferry_needs_enough_nights():
    short = engine.search([make_island()], cond(hub="tokyo", nights=3, budget_total=10**6))
    long = engine.search([make_island()], cond(hub="tokyo", nights=5, budget_total=10**6))
    assert not short.candidates
    assert long.candidates


def test_budget_filter_and_hint():
    result = engine.search([ONOMICHI], cond(budget_total=10000))
    assert not result.candidates
    gap, dest = engine.budget_hint(result.excluded, cond(budget_total=10000))
    assert gap > 0 and dest["id"] == "onomichi_shimanami"
    # ヒントどおり増やせば候補に入る
    assert engine.search([ONOMICHI], cond(budget_total=10000 + gap)).candidates


def test_bigger_budget_gets_better_lodging():
    tiers = [engine.estimate(ONOMICHI, cond(budget_total=b)).tier for b in (60000, 90000, 300000)]
    order = ["budget", "standard", "premium"]
    assert [order.index(t) for t in tiers] == sorted(order.index(t) for t in tiers)
    assert tiers[-1] == "premium"


def test_lodging_pref_budget_is_respected():
    est = engine.estimate(ONOMICHI, cond(budget_total=10**6, lodging_pref="budget"))
    assert est.tier == "budget"


def test_kids_cost_less_than_adults():
    three_adults = engine.estimate(ONOMICHI, cond(adults=3, kids=0, budget_total=10**6, lodging_pref="budget"))
    two_plus_kid = engine.estimate(ONOMICHI, cond(adults=2, kids=1, budget_total=10**6, lodging_pref="budget"))
    assert two_plus_kid.total < three_adults.total


def test_peak_season_costs_more():
    normal = engine.estimate(make_far_flight_only(), cond(start_date=date(2026, 10, 14), nights=2, budget_total=10**6))
    golden_week = engine.estimate(make_far_flight_only(), cond(start_date=date(2027, 5, 2), nights=2, budget_total=10**6))
    assert golden_week.breakdown["transport"] > normal.breakdown["transport"]
    assert golden_week.breakdown["lodging"] > normal.breakdown["lodging"]


def test_saturday_night_costs_more():
    wed = engine.estimate(ONOMICHI, cond(start_date=date(2026, 10, 14), budget_total=10**6, lodging_pref="budget"))
    sat = engine.estimate(ONOMICHI, cond(start_date=date(2026, 10, 17), budget_total=10**6, lodging_pref="budget"))
    assert sat.breakdown["lodging"] > wed.breakdown["lodging"]


def test_no_flight_excludes_flight_only_destination():
    result = engine.search([make_far_flight_only()], cond(nights=2, transport_pref="no_flight"))
    assert not result.candidates


def test_transport_pref_cheap_and_fast():
    opts = ONOMICHI["access"]["osaka"]  # 新幹線（速い・高い）と高速バス（遅い・安い）
    assert engine.choose_access(opts, cond(transport_pref="cheap"), date(2026, 10, 14))["mode"] == "bus"
    assert engine.choose_access(opts, cond(transport_pref="fast"), date(2026, 10, 14))["mode"] == "rail"


def test_scope_filter():
    fx = all_fixtures()
    domestic = engine.search(fx, cond(nights=2, budget_total=10**6, scope="domestic"))
    overseas = engine.search(fx, cond(nights=2, budget_total=10**6, scope="overseas"))
    assert "test_abroad" not in ids(domestic)
    assert ids(overseas) == {"test_abroad"}


def test_exclude_ids():
    result = engine.search(all_fixtures(), cond(nights=2, budget_total=10**6, exclude_ids=["onomichi_shimanami"]))
    assert "onomichi_shimanami" not in ids(result)


def test_genre_filter_is_hard_at_low_surprise_and_soft_at_high():
    fx = all_fixtures()
    strict = engine.search(fx, cond(nights=2, budget_total=10**6, genres=["beach"], surprise=2))
    loose = engine.search(fx, cond(nights=2, budget_total=10**6, genres=["beach"], surprise=5))
    assert all(c.dest["genres"].get("beach", 0) >= 2 for c in strict.candidates)
    assert len(loose.candidates) > len(strict.candidates)


# ── スコアと抽選 ──────────────────────────────────────────────────
def test_niche_preference_ranks_matching_destination_higher():
    fx = all_fixtures()
    niche5 = engine.search(fx, cond(nights=6, budget_total=10**6, niche=5, hub="tokyo"))
    niche1 = engine.search(fx, cond(nights=6, budget_total=10**6, niche=1, hub="tokyo"))
    score5 = {c.dest["id"]: c.score for c in niche5.candidates}
    score1 = {c.dest["id"]: c.score for c in niche1.candidates}
    assert score5["test_island"] > score1["test_island"]


def test_pick_is_deterministic_for_same_seed():
    result = engine.search(all_fixtures(), cond(nights=2, budget_total=10**6, scope="both"))
    a = [c.dest["id"] for c in engine.pick(result.candidates, 3, random.Random("x"), k=3)]
    b = [c.dest["id"] for c in engine.pick(result.candidates, 3, random.Random("x"), k=3)]
    assert a == b and len(set(a)) == 3


def test_low_surprise_mostly_picks_best_match():
    result = engine.search(all_fixtures(), cond(nights=2, budget_total=10**6, scope="both"))
    best = result.candidates[0].dest["id"]
    hits = sum(engine.pick(result.candidates, 1, random.Random(i))[0].dest["id"] == best for i in range(200))
    uniform = sum(engine.pick(result.candidates, 5, random.Random(i))[0].dest["id"] == best for i in range(200))
    assert hits > uniform


@pytest.mark.parametrize("nights", [0, 1, 3])
def test_explain_mentions_budget(nights):
    result = engine.search([ONOMICHI], cond(nights=nights))
    reasons = engine.explain(result.candidates[0], cond(nights=nights))
    assert any("予算" in r for r in reasons)


# ── レビュー指摘の回帰テスト ────────────────────────────────────────
def _with_night_bus(d: dict) -> dict:
    d = copy.deepcopy(d)
    d["access"]["osaka"] = [
        {"mode": "bus", "route": "大阪→（夜行バス）→尾道", "hours": 8.0, "cost": 3000, "overnight": True},
        {"mode": "rail", "route": "新大阪→（新幹線）→尾道", "hours": 1.7, "cost": 8500},
    ]
    return d


def test_cheap_pref_skips_overnight_option_on_short_trip():
    d = _with_night_bus(ONOMICHI)
    est = engine.estimate(d, cond(nights=1, transport_pref="cheap"))
    assert est.feasible
    assert est.access_out["mode"] == "rail" and est.access_back["mode"] == "rail"
    long = engine.estimate(d, cond(nights=3, transport_pref="cheap", budget_total=10**6))
    assert long.access_out.get("overnight") and long.access_back.get("overnight")


def test_explain_says_over_budget_honestly():
    result = engine.search([ONOMICHI], cond())
    reasons = engine.explain(result.candidates[0], cond(), total=cond().budget_total + 12345)
    assert any("オーバー" in r for r in reasons)
    assert not any("収まる" in r for r in reasons)


def test_explain_niche_wording_depends_on_gap_and_surprise():
    result = engine.search([ONOMICHI], cond(niche=1, surprise=1))  # ONOMICHI は 3
    text = " ".join(engine.explain(result.candidates[0], cond(niche=1, surprise=1)))
    assert "かなり" in text and "サプライズ枠" not in text
    text5 = " ".join(engine.explain(result.candidates[0], cond(niche=2, surprise=4)))
    assert "少し" in text5 and "サプライズ枠" in text5


def test_explain_mentions_relaxed_genre():
    result = engine.search([ONOMICHI], cond(genres=["beach"]))
    text = " ".join(engine.explain(result.candidates[0], cond(genres=["beach"]), genre_relaxed=True))
    assert "海・リゾート" in text and "問わず" in text
