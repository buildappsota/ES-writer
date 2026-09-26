"""行き先の絞り込み・スコアリング・抽選と、費用の見積もり。

旅程（1 日ごとの予定）は planner.py が組み立てる。ここでは
「どこへ行けるか」「どこが条件に合うか」「いくらかかるか」を扱う。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from .constants import GENRES, NICHE_LABELS, RELATIONS
from .rules import DINNER_BEFORE_RETURN, ON_BOARD_DINNER_FROM, back_times, in_scope, is_drink

# ── 費用モデルの係数（根拠は README の「費用の計算方法」を参照） ──────────
# 子ども（小学生以下）の費用倍率。鉄道の小児運賃は大人の半額、国内線の小児運賃は
# 各社とも大人普通運賃のおよそ半額〜早割並みのため 0.75 と保守的に置く。
KID_RATE = {"rail": 0.5, "bus": 0.5, "ferry": 0.5, "car": 0.0, "flight": 0.75,
            "lodging": 0.7, "food": 0.6, "spot": 0.5, "local": 0.5}

# 1 人 1 食あたりの基準額（全国平均的な価格帯。price_level と宿の段階で補正）
MEAL_BASE = {"breakfast": 900, "lunch": 1500, "dinner": 3000, "snack": 600}
FOOD_TIER_RATE = {"budget": 0.75, "standard": 1.0, "premium": 1.6}

# 宿の人数補正（schema の price は 2 名 1 室の 1 人あたり）
def occupancy_rate(people: int, tier: str) -> float:
    if people <= 1:
        return {"budget": 1.3, "standard": 1.4, "premium": 1.6}[tier]
    if people == 2:
        return 1.0
    if people <= 4:
        return 0.9
    return 0.85

# レンタカー 1 台 1 日あたり（コンパクトカー＋ガソリン代の目安）、1 台の定員
CAR_COST_PER_DAY = 9500
CAR_CAPACITY = 5

# 繁忙期（宿・航空券が高くなる時期）
PEAK_PERIODS = (((4, 29), (5, 6)), ((8, 10), (8, 17)), ((12, 28), (12, 31)), ((1, 1), (1, 3)))
PEAK_LODGING_RATE = 1.35
SATURDAY_LODGING_RATE = 1.15
PEAK_FLIGHT_RATE = 1.4

# 「おまかせ」で交通手段を選ぶときの時間の価値（円/時間/人）
TIME_VALUE_PER_HOUR = 2000

# 日帰りで許容する片道の所要時間、旅行全体で移動に使ってよい時間の割合
DAY_TRIP_MAX_HOURS = 3.5
MAX_TRAVEL_SHARE = 0.5
WAKING_HOURS_PER_DAY = 14

# サプライズ度 → ソフトマックス温度（None は完全ランダム）
SURPRISE_TEMPERATURE = {1: 0.02, 2: 0.05, 3: 0.1, 4: 0.2, 5: None}

SCORE_WEIGHTS = {"genre": 0.30, "niche": 0.25, "fit": 0.15, "season": 0.10,
                 "nights": 0.08, "travel": 0.07, "budget": 0.05}

SCORE_LABELS = {"genre": "ジャンル", "niche": "王道〜ニッチ", "fit": "関係性との相性",
                "season": "季節", "nights": "日数との相性", "travel": "移動の効率",
                "budget": "予算の使い方"}


@dataclass
class Conditions:
    """ユーザーが入力した条件。"""

    hub: str = "tokyo"
    start_date: date = field(default_factory=date.today)
    nights: int = 1
    adults: int = 2
    kids: int = 0
    relation: str = "friends"
    budget_total: int = 100000          # グループ全員の合計（円）
    genres: list[str] = field(default_factory=list)
    niche: int = 3
    detail: int = 3
    surprise: int = 2
    scope: str = "domestic"
    pace: str = "normal"
    transport_pref: str = "auto"
    lodging_pref: str = "auto"
    multi_stop: str = "auto"            # auto / off / on
    exclude_ids: list[str] = field(default_factory=list)

    @property
    def people(self) -> int:
        return self.adults + self.kids

    @property
    def days(self) -> int:
        return self.nights + 1

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.nights)

    def trip_months(self) -> set[int]:
        return {(self.start_date + timedelta(days=i)).month for i in range(self.days)}

    def fingerprint(self) -> tuple:
        """プランの内容に影響する条件（決め込み度は表示だけなので除く）。"""
        return (self.hub, self.start_date, self.nights, self.adults, self.kids, self.relation,
                self.budget_total, tuple(sorted(self.genres)), self.niche, self.surprise, self.scope,
                self.pace, self.transport_pref, self.lodging_pref, self.multi_stop,
                tuple(sorted(self.exclude_ids)))


# ════════════════════════════════════════════════════════════════════
# 費用
# ════════════════════════════════════════════════════════════════════
def is_peak(day: date) -> bool:
    for (m1, d1), (m2, d2) in PEAK_PERIODS:
        if (m1, d1) <= (day.month, day.day) <= (m2, d2):
            return True
    return False


def lodging_night_rate(night: date) -> float:
    """その夜の宿泊料金の倍率（繁忙期・土曜）。"""
    if is_peak(night):
        return PEAK_LODGING_RATE
    if night.weekday() == 5:
        return SATURDAY_LODGING_RATE
    return 1.0


def units(adults: int, kids: int, kind: str) -> float:
    """大人換算の人数。"""
    return adults + kids * KID_RATE[kind]


def access_cost(option: dict, cond: Conditions, travel_day: date) -> int:
    """片道の交通費（グループ合計）。"""
    mode = option["mode"]
    total = option["cost"] * units(cond.adults, cond.kids, mode if mode in KID_RATE else "rail")
    if mode == "flight" and is_peak(travel_day):
        total *= PEAK_FLIGHT_RATE
    return int(round(total, -1))


def effective_hours(option: dict) -> float:
    """起きている時間のうち移動に取られる時間。夜行は睡眠 8 時間ぶんを差し引く。"""
    return max(1.0, option["hours"] - 8) if option.get("overnight") else option["hours"]


def _pref_key(option: dict, pref: str) -> tuple:
    if pref == "cheap":
        return (option["cost"], option["hours"])
    if pref == "fast":
        return (option["hours"], option["cost"])
    return (option["cost"] + option["hours"] * TIME_VALUE_PER_HOUR,)


def legs_problems(out: dict, back: dict, cond: Conditions) -> list[str]:
    """行き・帰りの組み合わせが旅程として成り立たない理由。"""
    problems = []
    transit = int(bool(out.get("overnight"))) + int(bool(back.get("overnight")))
    if transit and cond.nights < transit + 1:
        problems.append("夜行の移動を含むため泊数が足りない")
    if cond.nights == 0 and max(out["hours"], back["hours"]) > DAY_TRIP_MAX_HOURS:
        problems.append(f"日帰りには遠い（片道 約{out['hours']:.1f} 時間）")
    if cond.nights > 0 and (effective_hours(out) + effective_hours(back)) \
            > cond.days * WAKING_HOURS_PER_DAY * MAX_TRAVEL_SHARE:
        problems.append(f"移動時間が旅程の半分を超える（片道 約{out['hours']:.1f} 時間）")
    return problems


def choose_legs(options: list[dict], cond: Conditions) -> tuple[dict, dict] | None:
    """移動手段の好みに合わせて、行きと帰りの行き方を選ぶ。

    旅程として成り立つ組み合わせ（夜行の泊数・日帰りの所要・移動時間の割合）の中から
    好みの順で選ぶ。成り立つものがなければ、好みでいちばんの組み合わせを返す
    （除外理由の表示に使う）。使える行き方がなければ None。
    """
    usable = [o for o in options if not (cond.transport_pref == "no_flight" and o["mode"] == "flight")]
    if not usable:
        return None
    combos = sorted(((o, b) for o in usable for b in usable),
                    key=lambda ob: tuple(x + y for x, y in zip(_pref_key(ob[0], cond.transport_pref),
                                                               _pref_key(ob[1], cond.transport_pref))))
    for out, back in combos:
        if not legs_problems(out, back, cond):
            return out, back
    return combos[0]


def choose_access(options: list[dict], cond: Conditions, travel_day: date | None = None) -> dict | None:
    """行きの行き方だけが必要なとき用（周遊の 2 か所目の帰りなど）。"""
    legs = choose_legs(options, cond)
    return legs[1] if legs else None


def meals_per_day_cost(dest: dict, tier: str) -> dict[str, float]:
    rate = dest["price_level"] * FOOD_TIER_RATE[tier]
    return {k: v * rate for k, v in MEAL_BASE.items()}


def local_transport_cost(dest: dict, cond: Conditions, days: int) -> int:
    lt = dest["local_transport"]
    if lt["car"]:
        cars = math.ceil(cond.people / CAR_CAPACITY)
        return int(round(CAR_COST_PER_DAY * cars * days, -1))
    return int(round(lt["cost_per_day"] * units(cond.adults, cond.kids, "local") * days, -1))


def lodging_cost(dest: dict, tier: str, cond: Conditions, nights: list[date]) -> int:
    lo = dest["lodging"][tier]
    per_person = lo["price"] * occupancy_rate(cond.people, tier)
    total = sum(per_person * lodging_night_rate(n) for n in nights)
    return int(round(total * units(cond.adults, cond.kids, "lodging"), -1))


NAMED_FOOD_TIER_RATE = {"budget": 0.85, "standard": 1.0, "premium": 1.3}
SPOTS_PER_DAY = {"relaxed": 2, "normal": 3, "packed": 4}
# 旅程側でいちばん強く節約したとき（planner.CAP_STEPS の最後）の上限。見積もりの下限計算に使う
FLOOR_SPOT_CAP = 0          # 有料スポットを外す（無料の見どころだけで回る）
FLOOR_MEAL_CAP = 1800
DRINK_CHANCE = 0.5          # お酒ジャンルを選んでいないとき、夕食に地酒などを添える確率


def generic_meal_cost(dest: dict, tier: str, slot: str, meal_cap: int | None = None) -> float:
    """名物がないときの 1 人 1 食の額。節約の上限があればそこで頭打ちにする。"""
    base = meals_per_day_cost(dest, tier)[slot]
    return min(base, meal_cap) if meal_cap is not None else base


def named_foods(dest: dict, slot: str, meal_cap: int | None = None) -> list[dict]:
    """その食事枠で使う名物（酒類を除く。節約の上限があれば、それ以下のものだけ）。"""
    return [f for f in dest["foods"] if f["meal"] == slot and not is_drink(f)
            and (meal_cap is None or f["price"] <= meal_cap)]


def meals_total(dest: dict, tier: str, slot: str, count: int, meal_cap: int | None = None) -> float:
    """その食事枠を count 回とるときの 1 人あたり合計。旅程と同じく名物を先に使い、尽きたら一般的な店。"""
    if count <= 0:
        return 0.0
    named = named_foods(dest, slot, meal_cap)
    k = min(count, len(named))
    avg = sum(f["price"] for f in named) / len(named) if named else 0
    return k * avg * NAMED_FOOD_TIER_RATE[tier] + (count - k) * generic_meal_cost(dest, tier, slot, meal_cap)


def sightseeing_days(cond: Conditions, out: dict, back: dict) -> int:
    """現地で過ごす日数（夜行の出発日・帰着日を除く）。"""
    return cond.days - int(bool(out.get("overnight"))) - int(bool(back.get("overnight")))


def return_meal(back: dict, tz: float) -> str | None:
    """帰る日の夕方の食事のとり方（旅程と同じ規則）。dinner＝現地で夕食 / quick＝車内などで軽く / None。"""
    depart, _ = back_times(back, tz)
    if depart >= DINNER_BEFORE_RETURN:
        return "dinner"
    if ON_BOARD_DINNER_FROM <= depart <= 21 * 60 and not back.get("overnight"):
        return "quick"
    if back.get("overnight"):   # 昼に出る長い船旅：船内で夕食
        return "quick"
    return None


def onboard_meals(option: dict) -> int:
    """長い夜行（16 時間以上）の船・バスの中でとる食事の回数。"""
    return 2 if option.get("overnight") and option["hours"] >= 16 else 0


def food_estimate(dest: dict, tier: str, cond: Conditions, out: dict, back: dict, lodging_nights: int,
                  meal_cap: int | None = None, drinks: bool = True, snacks: bool = True) -> int:
    """食費の見積もり。旅程と同じ規則で、何をいくつ食べるかを数える。"""
    days = sightseeing_days(cond, out, back)
    included = dest["lodging"][tier]["meals"] if lodging_nights else 0
    tz = dest.get("tz_offset", 0)
    quick = generic_meal_cost(dest, tier, "lunch", meal_cap)
    per_person = meals_total(dest, tier, "lunch", days, meal_cap)
    if snacks:
        per_person += meals_total(dest, tier, "snack", min(days, len(named_foods(dest, "snack", meal_cap))), meal_cap)
    breakfasts = (lodging_nights if included < 1 else 0) + (1 if out.get("overnight") else 0)
    per_person += meals_total(dest, tier, "breakfast", breakfasts, meal_cap)
    dinners = lodging_nights if included < 2 else 0
    last = return_meal(back, tz)
    dinners += last == "dinner"
    per_person += meals_total(dest, tier, "dinner", dinners, meal_cap)
    per_person += quick * ((last == "quick") + onboard_meals(out) + onboard_meals(back))
    total = per_person * units(cond.adults, cond.kids, "food")
    if drinks:
        drink_list = [f for f in dest["foods"] if is_drink(f)]
        eligible = min(lodging_nights + (last == "dinner"), len(drink_list))
        if drink_list and eligible:
            avg = sum(f["price"] for f in drink_list) / len(drink_list)
            chance = 1.0 if "drink" in cond.genres else DRINK_CHANCE
            total += eligible * avg * cond.adults * chance
    return int(round(total, -1))


def activities_estimate(dest: dict, cond: Conditions, days: int, spot_cap: int | None = None) -> int:
    """入場料・体験料の見積もり。1 日に回る数 × 日数（スポット数が上限）× 代表的な料金。

    料金は平均と中央値の中間をとる（高額ツアーが 1〜2 件あるだけで膨らまないように）。
    """
    costs = sorted(s["cost"] for s in dest["spots"] if spot_cap is None or s["cost"] <= spot_cap)
    if not costs:
        return 0
    mean = sum(costs) / len(costs)
    median = costs[len(costs) // 2]
    visits = min(SPOTS_PER_DAY[cond.pace] * max(1, days), len(costs))
    return int(round(visits * (mean + median) / 2 * units(cond.adults, cond.kids, "spot"), -1))


@dataclass
class Estimate:
    """行き先 1 件の概算（旅程を組む前の見積もり）。"""

    dest: dict
    tier: str | None
    access_out: dict | None
    access_back: dict | None
    breakdown: dict[str, int]
    total: int                      # 期待値（宿の段階はこれで選ぶ）
    feasible: bool
    reasons_excluded: list[str]
    one_way_hours: float
    transit_nights: int
    floor: int = 0                  # いちばん節約したときの見込み（予算で絞り込むときはこちら）
    cheap_legs: tuple[dict, dict] | None = None   # 節約するときに使う行き方


def stay_nights(cond: Conditions, out: dict, back: dict) -> list[date]:
    """宿に泊まる夜の日付（往路が夜行なら初日の夜、復路が夜行なら最終夜を除く）。"""
    nights = [cond.start_date + timedelta(days=i) for i in range(cond.nights)]
    if out.get("overnight"):
        nights = nights[1:]
    if back.get("overnight"):
        nights = nights[:-1]
    return nights


def cheapest_legs(options: list[dict], cond: Conditions) -> tuple[dict, dict] | None:
    """旅程として成り立つ中でいちばん安い行き方（速さ優先のときは好みを尊重して使わない）。"""
    if cond.transport_pref == "fast":
        return None
    usable = [o for o in options if not (cond.transport_pref == "no_flight" and o["mode"] == "flight")]
    combos = sorted(((o, b) for o in usable for b in usable), key=lambda ob: (ob[0]["cost"] + ob[1]["cost"],
                                                                            ob[0]["hours"] + ob[1]["hours"]))
    return next(((o, b) for o, b in combos if not legs_problems(o, b, cond)), None)


def _breakdown(dest: dict, cond: Conditions, tier: str, out: dict, back: dict, spot_cap: int | None = None,
               meal_cap: int | None = None, drinks: bool = True, snacks: bool = True) -> dict[str, int]:
    nights = stay_nights(cond, out, back)
    days = sightseeing_days(cond, out, back)
    return {
        "transport": access_cost(out, cond, cond.start_date) + access_cost(back, cond, cond.end_date),
        "lodging": lodging_cost(dest, tier, cond, nights) if nights else 0,
        "food": food_estimate(dest, tier, cond, out, back, len(nights), meal_cap, drinks, snacks),
        "local": local_transport_cost(dest, cond, days),
        "activities": activities_estimate(dest, cond, days, spot_cap),
    }


def estimate(dest: dict, cond: Conditions, tier_override: str | None = None) -> Estimate:
    """旅程を組む前の概算。

    宿は、期待値で予算に収まるいちばん良い段階を選ぶ。予算で絞り込むときは、旅程側で
    できる節約（宿を節約に・高額な体験や料理を外す・安い行き方）をすべてしたときの見込み
    （floor）で判定する。こうすると「見積もりでは無理なのに旅程では組める」行き先を落とさない。
    """
    excluded: list[str] = []
    options = dest["access"].get(cond.hub, [])
    legs = choose_legs(options, cond)
    if legs is None:
        return Estimate(dest, None, None, None, {}, 0, False, ["移動手段の条件に合う行き方がない"], 0.0, 0)
    out, back = legs

    if cond.nights < dest["min_nights"]:
        excluded.append(f"最低 {dest['min_nights']} 泊は必要")
    excluded += legs_problems(out, back, cond)
    bad_months = cond.trip_months() & set(dest["avoid_months"])
    if bad_months:
        excluded.append(f"{'・'.join(str(m) for m in sorted(bad_months))}月は現実的でない（閉鎖・運休など）")

    tiers = ["premium", "standard", "budget"]
    if tier_override:
        tiers = [tier_override]
    elif cond.lodging_pref != "auto":
        tiers = tiers[tiers.index(cond.lodging_pref):]

    cheap = cheapest_legs(options, cond)
    chosen = None
    for tier in tiers:
        breakdown = _breakdown(dest, cond, tier, out, back)
        if sum(breakdown.values()) <= cond.budget_total:
            chosen = (tier, breakdown)
            break
    if chosen is None and cheap is not None and cheap != (out, back) and cond.transport_pref == "auto":
        # 好みの行き方では収まらないが、安い行き方なら収まる → 安い行き方にする
        for tier in tiers:
            breakdown = _breakdown(dest, cond, tier, *cheap)
            if sum(breakdown.values()) <= cond.budget_total:
                out, back = cheap
                chosen = (tier, breakdown)
                break
    if chosen is None:
        chosen = (tiers[-1], _breakdown(dest, cond, tiers[-1], out, back))
    tier, breakdown = chosen
    total = sum(breakdown.values())

    floor_legs = cheap or (out, back)
    floor = sum(_breakdown(dest, cond, tiers[-1], *floor_legs, spot_cap=FLOOR_SPOT_CAP,
                           meal_cap=FLOOR_MEAL_CAP, drinks=False, snacks=False).values())
    if floor > cond.budget_total:
        excluded.append(f"予算オーバー（いちばん節約しても約 {floor:,} 円かかる見込み）")

    transit = int(bool(out.get("overnight"))) + int(bool(back.get("overnight")))
    return Estimate(dest, tier, out, back, breakdown, total, not excluded, excluded, out["hours"], transit,
                    floor=floor, cheap_legs=cheap)


# ════════════════════════════════════════════════════════════════════
# スコアリング
# ════════════════════════════════════════════════════════════════════
def genre_score(dest_genres: dict[str, int], wanted: list[str]) -> float:
    if not wanted:
        return 0.5
    strengths = [dest_genres.get(g, 0) / 3 for g in wanted]
    return 0.6 * (sum(strengths) / len(strengths)) + 0.4 * max(strengths)


def niche_score(value: int, wanted: int) -> float:
    closeness = 1 - abs(value - wanted) / 4
    return closeness ** 2


def score_destination(est: Estimate, cond: Conditions) -> dict[str, float]:
    d = est.dest
    lo, hi = d["ideal_nights"]
    if lo <= cond.nights <= hi:
        nights = 1.0
    else:
        gap = lo - cond.nights if cond.nights < lo else cond.nights - hi
        nights = max(0.2, 1 - 0.25 * gap)
    travel_share = (effective_hours(est.access_out) + effective_hours(est.access_back)) / (cond.days * WAKING_HOURS_PER_DAY)
    usage = est.total / cond.budget_total if cond.budget_total else 1
    # 予算の 55〜100% を使う行き先を少しだけ優先（安すぎても減点は小さい）
    budget = 1.0 if 0.55 <= usage <= 1.0 else (0.5 + usage if usage < 0.55 else 0.0)
    months = cond.trip_months()
    return {
        "genre": genre_score(d["genres"], cond.genres),
        "niche": niche_score(d["niche"], cond.niche),
        "fit": d["fit"][cond.relation] / 3,
        "season": 1.0 if months & set(d["best_months"]) else 0.5,
        "nights": nights,
        "travel": max(0.0, 1 - travel_share * 1.5),
        "budget": min(1.0, budget),
    }


def total_score(parts: dict[str, float]) -> float:
    return sum(SCORE_WEIGHTS[k] * v for k, v in parts.items())


@dataclass
class Candidate:
    est: Estimate
    parts: dict[str, float]
    score: float

    @property
    def dest(self) -> dict:
        return self.est.dest


@dataclass
class Search:
    """候補探索の結果。"""

    candidates: list[Candidate]           # 条件を満たす行き先（スコア順）
    excluded: list[Estimate]              # 条件を満たさなかった行き先
    genre_relaxed: bool                   # ジャンル条件をゆるめたか（genre_level == 0）
    scope_count: int                      # 範囲（国内/海外）内の行き先数
    genre_level: int | None = None        # 2=希望ジャンルが強い所だけ / 1=少し楽しめる所まで / 0=問わず / None=絞っていない
    premium_missing: bool = False         # 「贅沢したい」なのに贅沢な宿が予算内の行き先がなかった

    @property
    def niches(self) -> set[int]:
        return {c.dest["niche"] for c in self.candidates}

    def info(self) -> dict:
        return {"scope_count": self.scope_count, "candidates": len(self.candidates),
                "genre_level": self.genre_level, "premium_missing": self.premium_missing,
                "niches": sorted(self.niches)}


def _genre_ok(dest: dict, wanted: list[str], min_strength: int) -> bool:
    return any(dest["genres"].get(g, 0) >= min_strength for g in wanted)


def search(destinations: list[dict], cond: Conditions) -> Search:
    """条件で絞り込み、スコア順の候補を返す。"""
    pool = [d for d in destinations if d["id"] not in cond.exclude_ids and in_scope(d, cond.scope)]
    estimates = [estimate(d, cond) for d in pool]
    feasible = [e for e in estimates if e.feasible]
    excluded = [e for e in estimates if not e.feasible]

    genre_level = None
    if cond.genres and cond.surprise <= 3:
        for level in (2, 1):
            matched = [e for e in feasible if _genre_ok(e.dest, cond.genres, level)]
            if matched:
                feasible, genre_level = matched, level
                break
        else:
            genre_level = 0 if feasible else None

    premium_missing = False
    if cond.lodging_pref == "premium" and cond.nights > 0 and cond.surprise <= 3 and feasible:
        premium = [e for e in feasible if e.tier == "premium"]
        if premium:
            feasible = premium
        else:
            premium_missing = True

    candidates = []
    for e in feasible:
        parts = score_destination(e, cond)
        candidates.append(Candidate(e, parts, total_score(parts)))
    candidates.sort(key=lambda c: c.score, reverse=True)
    return Search(candidates, excluded, genre_level == 0, len(pool), genre_level, premium_missing)


def pick(candidates: list[Candidate], surprise: int, rng: random.Random, k: int = 1) -> list[Candidate]:
    """スコアとサプライズ度に応じて重み付き抽選する（重複なしで k 件）。"""
    pool = list(candidates)
    chosen: list[Candidate] = []
    temp = SURPRISE_TEMPERATURE[surprise]
    while pool and len(chosen) < k:
        if temp is None:
            idx = rng.randrange(len(pool))
        else:
            top = max(c.score for c in pool)
            weights = [math.exp((c.score - top) / temp) for c in pool]
            idx = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        chosen.append(pool.pop(idx))
    return chosen


def budget_hint(excluded: list[Estimate], cond: Conditions) -> tuple[int, dict] | None:
    """予算だけが理由で外れた行き先のうち、あといくら（節約した場合）で届くかが最小のもの。"""
    only_budget = [e for e in excluded
                   if len(e.reasons_excluded) == 1 and e.reasons_excluded[0].startswith("予算オーバー")]
    if not only_budget:
        return None
    e = min(only_budget, key=lambda e: e.floor)
    gap = e.floor - cond.budget_total
    return (gap, e.dest) if gap > 0 else None


def explain(cand: Candidate, cond: Conditions, total: int | None = None, genre_relaxed: bool = False,
            info: dict | None = None) -> list[str]:
    """この行き先が選ばれた理由（人が読める形）。条件に合っていない点も、理由とともに正直に書く。

    info は Search.info()（ジャンルをどこまでゆるめたか、候補にあったニッチ度など）。
    """
    info = info or {}
    d = cand.dest
    reasons = []
    level = 0 if genre_relaxed else info.get("genre_level")
    if cond.genres:
        wanted = "・".join(GENRES[g] for g in cond.genres)
        best = max(d["genres"].get(g, 0) for g in cond.genres)
        hits = [GENRES[g] for g in cond.genres if d["genres"].get(g, 0) >= 2]
        if hits:
            reasons.append(f"希望ジャンルのうち「{'・'.join(hits)}」が強い")
        elif best == 1:
            why = ("強く合う行き先が条件内になかったため" if level == 1
                   else "サプライズ度が高く、ジャンルを外れた候補も抽選に入るため")
            reasons.append(f"希望ジャンル（{wanted}）は少しだけ楽しめる程度（{why}）")
        else:
            why = ("合う行き先が条件内になかったため" if level == 0
                   else "サプライズ度が高く、ジャンルを外れた候補も抽選に入るため")
            reasons.append(f"希望ジャンル（{wanted}）とは別の楽しみ方の場所（{why}）")
    else:
        top = sorted(d["genres"].items(), key=lambda kv: -kv[1])[:2]
        reasons.append(f"ジャンルおまかせ → 「{'・'.join(GENRES[g] for g, _ in top)}」が持ち味の場所")

    diff = d["niche"] - cond.niche
    label = NICHE_LABELS[d["niche"]]
    if diff == 0:
        reasons.append(f"王道〜ニッチの好み（{NICHE_LABELS[cond.niche]}）にぴったり")
    else:
        direction = "ニッチ寄り" if diff > 0 else "王道寄り"
        degree = "少し" if abs(diff) == 1 else "かなり"
        niches = info.get("niches")
        closer_existed = niches is not None and any(abs(n - cond.niche) < abs(diff) for n in niches)
        if niches is not None and not closer_existed:
            why = "条件を満たす行き先の中に、好みにもっと近いものがなかったため"
        elif cond.surprise >= 3:
            why = "サプライズ枠"
        else:
            why = "スコアの重み付き抽選で選ばれた。好みにより近い候補も「他の候補」から選べる"
        reasons.append(f"好みより{degree}{direction}の「{label}」（{why}）")

    if cond.trip_months() & set(d["best_months"]):
        reasons.append("旅行する月がベストシーズン")
    fit = d["fit"][cond.relation]
    if fit >= 3:
        reasons.append(f"{RELATIONS[cond.relation]}との相性がとても良い")
    elif fit <= 1:
        reasons.append(f"{RELATIONS[cond.relation]}向けの定番ではない（意外性枠）")
    if info.get("premium_missing"):
        reasons.append("贅沢な宿で予算に収まる行き先がなかったため、宿の段階は予算に合わせた")

    total = cand.est.total if total is None else total
    if cond.budget_total and total > cond.budget_total:
        reasons.append(f"概算は予算を約 {total - cond.budget_total:,} 円オーバー")
    elif cond.budget_total:
        reasons.append(f"概算で予算の {total / cond.budget_total * 100:.0f}% に収まる")
    return reasons
