import copy
from datetime import date

import pytest

from tests.fixtures import ONOMICHI, all_fixtures, make_island, make_kurashiki
from trip_maker import engine, planner, render
from trip_maker.engine import Conditions


def cond(**kw) -> Conditions:
    base = dict(hub="osaka", start_date=date(2026, 10, 14), nights=2, adults=2, kids=0, relation="couple",
                budget_total=300000, genres=["town"], niche=3, surprise=2)
    base.update(kw)
    return Conditions(**base)


def make(c: Conditions, dests=None, dest_id="onomichi_shimanami", seed=1) -> planner.Plan:
    dests = dests or all_fixtures()
    result = engine.search(dests, c)
    cand = next(x for x in result.candidates if x.dest["id"] == dest_id)
    return planner.make_plan(cand, c, dests, seed, seed + 1)


def assert_no_overlap(plan: planner.Plan) -> None:
    for day in plan.days:
        timed = [b for b in day.blocks if b.end > b.start and b.kind != "travel"]
        for a, b in zip(timed, timed[1:]):
            assert a.end <= b.start, (day.number, a.title, planner.fmt_time(a.end), b.title, planner.fmt_time(b.start))


@pytest.mark.parametrize("nights", [0, 1, 2, 3, 5])
@pytest.mark.parametrize("pace", ["relaxed", "normal", "packed"])
def test_plan_invariants(nights, pace):
    plan = make(cond(nights=nights, pace=pace))
    assert len(plan.days) == nights + 1
    assert plan.total == sum(plan.costs.values())
    assert_no_overlap(plan)
    spot_names = [b.title for d in plan.days for b in d.blocks if b.kind == "spot"]
    assert len(spot_names) == len(set(spot_names)), "同じスポットを 2 回訪れている"
    lodging_nights = sum(1 for d in plan.days if d.lodging)
    assert lodging_nights == nights


def test_day_trip_has_no_lodging_and_returns_home():
    plan = make(cond(nights=0))
    assert plan.costs["lodging"] == 0
    assert plan.days[0].kind == "daytrip"
    assert plan.days[0].blocks[-1].kind == "travel"


def test_return_route_is_reversed():
    plan = make(cond(nights=1))
    last = plan.days[-1].blocks[-1]
    assert last.title.startswith("帰路：尾道")


def test_same_seed_same_plan():
    a, b = make(cond()), make(cond())
    assert render.to_markdown(a, 5) == render.to_markdown(b, 5)


def test_different_plan_seed_can_change_plan():
    c = cond(nights=3, surprise=4)
    result = engine.search(all_fixtures(), c)
    cand = next(x for x in result.candidates if x.dest["id"] == "onomichi_shimanami")
    outputs = {render.days_md(planner.make_plan(cand, c, all_fixtures(), 1, s), 3) for s in range(8)}
    assert len(outputs) > 1


def test_ryokan_day_ends_sightseeing_before_checkin():
    plan = make(cond(nights=1, lodging_pref="premium", budget_total=10**6))
    assert plan.tier == "premium"
    day1 = plan.days[0]
    checkin = next(b for b in day1.blocks if b.kind == "lodging")
    assert checkin.start == 17 * 60
    assert all(b.end <= checkin.start for b in day1.blocks if b.kind in ("spot", "free", "snack"))
    assert any(b.title == "夕食（宿）" for b in day1.blocks)


def test_multi_stop_for_long_trip():
    plan = make(cond(nights=5, multi_stop="on"))
    assert [s.dest["id"] for s in plan.stops] == ["onomichi_shimanami", "kurashiki"]
    assert plan.transfer is not None
    assert any(d.kind == "transfer" for d in plan.days)
    assert sum(s.nights for s in plan.stops) == 5
    assert_no_overlap(plan)


def test_multi_stop_off():
    plan = make(cond(nights=5, multi_stop="off"))
    assert len(plan.stops) == 1


def test_overnight_ferry_trip_structure():
    c = cond(hub="tokyo", nights=5, genres=[], budget_total=10**6)
    plan = make(c, dests=[make_island()], dest_id="test_island")
    kinds = [d.kind for d in plan.days]
    assert kinds[0] == "transit" and kinds[-1] == "home"
    assert sum(1 for d in plan.days if d.lodging) == 3  # 5 泊のうち 2 泊は船中
    assert plan.costs["lodging"] > 0
    assert_no_overlap(plan)


def test_over_budget_downgrades_lodging():
    c = cond(nights=2, budget_total=10**6)
    result = engine.search(all_fixtures(), c)
    cand = next(x for x in result.candidates if x.dest["id"] == "onomichi_shimanami")
    assert cand.est.tier == "premium"
    tight = cond(nights=2, budget_total=int(cand.est.total * 0.6))
    plan = planner.make_plan(cand, tight, all_fixtures(), 1, 2)
    assert plan.tier != "premium"
    assert plan.tier_note


def test_family_kids_skip_avoided_spots():
    d = copy.deepcopy(ONOMICHI)
    for s in d["spots"]:
        s["avoid"] = ["family_kids"] if s["name"] == "猫の細道" else []
    c = cond(relation="family_kids", adults=2, kids=2, nights=3, multi_stop="off")
    plan = make(c, dests=[d, make_kurashiki()])
    assert all(b.title != "猫の細道" for day in plan.days for b in day.blocks)


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_render_levels(level):
    plan = make(cond(nights=2))
    md = render.to_markdown(plan, level)
    assert plan.title in md
    assert ("## 旅程" in md) == (level >= 3)
    assert ("## 持ち物リスト" in md) == (level >= 5)
    assert ("## アクセス" in md) == (level >= 2)
    if level >= 4:
        assert "| 時刻 |" in md
    prompt = render.claude_prompt(plan, level)
    assert "要確認" in prompt and plan.title in prompt


def test_trip_code_format():
    plan = make(cond())
    a, b = plan.trip_code.split("-")
    assert int(a) == plan.dest_seed and int(b) == plan.plan_seed


@pytest.mark.parametrize("tz,hours,arrive,depart", [(-2, 8.5, "13:30", "10:30"), (-19, 10.0, "12:00", "16:00"),
                                                    (0, 5.0, "12:00", "16:00")])
def test_overseas_times_use_local_time(tz, hours, arrive, depart):
    from tests.fixtures import make_overseas
    d = make_overseas()
    if tz:
        d["tz_offset"] = tz
    for hub in d["access"]:
        d["access"][hub][0]["hours"] = hours
    c = cond(hub="tokyo", nights=4, scope="overseas", genres=[], budget_total=10**6)
    plan = make(c, dests=[d], dest_id="test_abroad")
    first = next(b for b in plan.days[0].blocks if b.kind == "travel")
    last = [b for b in plan.days[-1].blocks if b.kind == "travel"][-1]
    assert planner.fmt_time(first.end) == arrive
    assert planner.fmt_time(last.start) == depart
    if tz == -19:
        assert "日本時間 21:00 発" in first.detail
        assert "翌21:00" in last.detail  # 日付変更線をまたいで翌日帰着
    assert_no_overlap(plan)


def test_closed_weekday_is_respected():
    d = copy.deepcopy(ONOMICHI)
    for s in d["spots"]:
        s["closed"] = [2]  # すべて水曜定休
    c = cond(nights=0, start_date=date(2026, 10, 14), genres=[])  # 水曜日
    plan = make(c, dests=[d])
    assert not [b for b in plan.days[0].blocks if b.kind == "spot"]
    thursday = make(cond(nights=0, start_date=date(2026, 10, 15), genres=[]), dests=[d])
    assert [b for b in thursday.days[0].blocks if b.kind == "spot"]


def test_lodging_label_does_not_repeat_meals():
    assert planner.lodging_label({"type": "民宿（1泊2食）", "meals": 2}) == "民宿（1泊2食）"
    assert planner.lodging_label({"type": "ビジネスホテル", "meals": 0}) == "ビジネスホテル（素泊まり）"


def test_drinks_are_added_to_dinner_not_served_as_meals():
    d = copy.deepcopy(ONOMICHI)
    d["foods"].append({"name": "瀬戸内の地酒", "price": 800, "meal": "dinner", "note": "テスト"})
    d["foods"].append({"name": "甘酒", "price": 300, "meal": "snack", "note": "ノンアルコール"})
    c = cond(nights=3, genres=["drink"], multi_stop="off")
    plan = make(c, dests=[d, make_kurashiki()])
    titles = [b.title for day in plan.days for b in day.blocks if b.kind in ("meal", "snack")]
    assert "夕食：瀬戸内の地酒" not in titles
    assert any("（＋瀬戸内の地酒）" in t for t in titles)
    assert not planner.is_drink({"name": "甘酒"})


# ── レビュー指摘の回帰テスト ────────────────────────────────────────
from tests.invariants import violations  # noqa: E402


def _expensive(d: dict) -> dict:
    d = copy.deepcopy(d)
    d["foods"].append({"name": "高級カニ会席", "price": 15000, "meal": "dinner", "note": "テスト"})
    for s in d["spots"]:
        if s["name"].startswith("しまなみ"):
            s["cost"] = 12000
    return d


def test_over_budget_plan_is_trimmed_to_fit():
    d = _expensive(ONOMICHI)
    c = cond(nights=1, genres=["activity"], lodging_pref="budget", budget_total=10**6)
    rich = make(c, dests=[d])
    tight = cond(nights=1, genres=["activity"], lodging_pref="budget", budget_total=int(rich.total * 0.8))
    result = engine.search([d], tight)
    plan = planner.make_plan(result.candidates[0], tight, [d], 1, 2)
    assert not plan.over_budget, (plan.total, tight.budget_total)
    assert plan.tier_note and "予算に収める" in plan.tier_note


def test_candidates_fallback_when_first_does_not_fit():
    d = _expensive(ONOMICHI)
    cheap = make_kurashiki()
    c = cond(nights=1, genres=[], lodging_pref="budget", budget_total=10**6)
    first = planner.make_plan(engine.search([d], c).candidates[0], c, [d], 1, 2)
    budget = first.total - 1  # 1 か所目は削っても……とはならないよう、上限なしの旅程より 1 円だけ少ない
    tight = cond(nights=1, genres=[], lodging_pref="budget", budget_total=budget)
    cands = engine.search([d, cheap], tight).candidates
    cands.sort(key=lambda x: x.dest["id"] != "onomichi_shimanami")
    plan = planner.make_plan_from_candidates(cands, tight, [d, cheap], 1, 2)
    assert not plan.over_budget


def test_trip_code_roundtrip():
    assert planner.parse_trip_code("123-456") == (123, 456, None)
    assert planner.parse_trip_code("123-456-onomichi_shimanami") == (123, 456, "onomichi_shimanami")
    assert planner.parse_trip_code("123456") is None
    assert planner.parse_trip_code("abc-def") is None
    c = cond()
    result = engine.search(all_fixtures(), c)
    forced = next(x for x in result.candidates if x.dest["id"] == "kurashiki")
    plan = planner.make_plan(forced, c, all_fixtures(), 5, 6, forced=True)
    assert plan.trip_code == "5-6-kurashiki"


def test_plan_reroll_keeps_second_stop():
    c = cond(nights=5, multi_stop="on")
    result = engine.search(all_fixtures(), c)
    cand = next(x for x in result.candidates if x.dest["id"] == "onomichi_shimanami")
    stops = {tuple(s.dest["id"] for s in planner.make_plan(cand, c, all_fixtures(), 9, ps).stops) for ps in range(6)}
    assert len(stops) == 1


def test_day_trip_booking_list_has_no_lodging():
    plan = make(cond(nights=0))
    assert not any(b.startswith("宿：") for b in plan.bookings)


def test_level3_keeps_highlights_and_prompt_follows_level():
    plan = make(cond(nights=2))
    assert "## 見どころ" in render.to_markdown(plan, 3)
    low = render.claude_prompt(plan, 1)
    assert "| 時刻 |" not in low and "決め込み度：行き先だけ" in low
    assert "| 時刻 |" in render.claude_prompt(plan, 4)


def test_late_arrival_checks_in_after_arriving():
    d = copy.deepcopy(ONOMICHI)
    for hub in d["access"]:
        d["access"][hub] = [{"mode": "rail", "route": "遠い駅→（在来線）→尾道", "hours": 11.0, "cost": 20000}]
    c = cond(nights=3, genres=[])
    plan = make(c, dests=[d])
    day1 = plan.days[0]
    arrive = next(b for b in day1.blocks if b.kind == "travel").end
    checkin = next(b for b in day1.blocks if b.kind == "lodging")
    assert checkin.start >= arrive
    assert violations(plan) == []


def test_time_window_rules_on_fixtures():
    d = copy.deepcopy(ONOMICHI)
    d["spots"].append({"name": "朝市", "area": "尾道市街", "kind": "market", "genres": ["gourmet"], "niche": 3,
                       "hours": 1.0, "cost": 0, "when": ["morning"], "indoor": False, "fit": [], "note": "テスト"})
    for nights in (0, 1, 2, 3):
        for seed in range(5):
            c = cond(nights=nights, genres=["gourmet", "town"], surprise=3)
            plan = make(c, dests=[d, make_kurashiki()], seed=seed)
            assert violations(plan) == [], violations(plan)
