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

# 見どころの入場料・体験料の事前見積もり（1 人 1 日あたり）
ACTIVITY_ESTIMATE_PER_DAY = 1500

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


def choose_access(options: list[dict], cond: Conditions, travel_day: date) -> dict | None:
    """移動手段の好みに合わせて行き方を 1 つ選ぶ。候補がなければ None。"""
    usable = [o for o in options if not (cond.transport_pref == "no_flight" and o["mode"] == "flight")]
    if not usable:
        return None
    if cond.transport_pref == "cheap":
        return min(usable, key=lambda o: (o["cost"], o["hours"]))
    if cond.transport_pref == "fast":
        return min(usable, key=lambda o: (o["hours"], o["cost"]))
    return min(usable, key=lambda o: o["cost"] + o["hours"] * TIME_VALUE_PER_HOUR)


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


def food_estimate(dest: dict, tier: str, cond: Conditions, days: int, lodging_nights: int) -> int:
    """食費の見積もり。宿に含まれる食事（朝食・夕食）は差し引く。"""
    m = meals_per_day_cost(dest, tier)
    per_person = (m["breakfast"] + m["lunch"] + m["dinner"] + m["snack"]) * days
    meals_included = dest["lodging"][tier]["meals"] if lodging_nights else 0
    if meals_included >= 1:
        per_person -= m["breakfast"] * lodging_nights
    if meals_included >= 2:
        per_person -= m["dinner"] * lodging_nights
    if lodging_nights == 0:  # 日帰りは朝食を家で済ませる前提
        per_person -= m["breakfast"] * days
    return int(round(per_person * units(cond.adults, cond.kids, "food"), -1))


@dataclass
class Estimate:
    """行き先 1 件の概算（旅程を組む前の見積もり）。"""

    dest: dict
    tier: str | None
    access_out: dict | None
    access_back: dict | None
    breakdown: dict[str, int]
    total: int
    feasible: bool
    reasons_excluded: list[str]
    one_way_hours: float
    transit_nights: int


def stay_nights(cond: Conditions, out: dict, back: dict) -> list[date]:
    """宿に泊まる夜の日付（往路が夜行なら初日の夜、復路が夜行なら最終夜を除く）。"""
    nights = [cond.start_date + timedelta(days=i) for i in range(cond.nights)]
    if out.get("overnight"):
        nights = nights[1:]
    if back.get("overnight"):
        nights = nights[:-1]
    return nights


def estimate(dest: dict, cond: Conditions, tier_override: str | None = None) -> Estimate:
    """旅程を組む前の概算。宿は予算内でいちばん良い段階を選ぶ。"""
    excluded: list[str] = []
    opts = dest["access"].get(cond.hub, [])
    out = choose_access(opts, cond, cond.start_date)
    back = choose_access(opts, cond, cond.end_date)
    if out is None or back is None:
        return Estimate(dest, None, None, None, {}, 0, False, ["移動手段の条件に合う行き方がない"], 0.0, 0)

    transit = int(bool(out.get("overnight"))) + int(bool(back.get("overnight")))
    hours = out["hours"]
    nights_at_stay = stay_nights(cond, out, back)
    days = cond.days

    if cond.nights < dest["min_nights"]:
        excluded.append(f"最低 {dest['min_nights']} 泊は必要")
    if transit and cond.nights < transit + 1:
        excluded.append("夜行の移動を含むため泊数が足りない")
    if cond.nights == 0 and hours > DAY_TRIP_MAX_HOURS:
        excluded.append(f"日帰りには遠い（片道 約{hours:.1f} 時間）")
    if cond.nights > 0 and (effective_hours(out) + effective_hours(back)) > days * WAKING_HOURS_PER_DAY * MAX_TRAVEL_SHARE:
        excluded.append(f"移動時間が旅程の半分を超える（片道 約{hours:.1f} 時間）")
    bad_months = cond.trip_months() & set(dest["avoid_months"])
    if bad_months:
        excluded.append(f"{'・'.join(str(m) for m in sorted(bad_months))}月は現実的でない（閉鎖・運休など）")

    transport = access_cost(out, cond, cond.start_date) + access_cost(back, cond, cond.end_date)
    local = local_transport_cost(dest, cond, days)
    activities = int(round(ACTIVITY_ESTIMATE_PER_DAY * dest["price_level"] * days
                           * units(cond.adults, cond.kids, "spot"), -1))

    tiers = ["premium", "standard", "budget"]
    if tier_override:
        tiers = [tier_override]
    elif cond.lodging_pref != "auto":
        start = tiers.index(cond.lodging_pref)
        tiers = tiers[start:]

    best: tuple[str, dict[str, int], int] | None = None
    fallback: tuple[str, dict[str, int], int] | None = None
    for tier in tiers:
        lodging = lodging_cost(dest, tier, cond, nights_at_stay) if nights_at_stay else 0
        food = food_estimate(dest, tier, cond, days, len(nights_at_stay))
        breakdown = {"transport": transport, "lodging": lodging, "food": food,
                     "local": local, "activities": activities}
        total = sum(breakdown.values())
        fallback = (tier, breakdown, total)
        if total <= cond.budget_total:
            best = (tier, breakdown, total)
            break
    if best is None:
        tier, breakdown, total = fallback  # いちばん安い段階でも予算超過
        excluded.append(f"予算オーバー（最安でも約 {total:,} 円）")
    else:
        tier, breakdown, total = best

    return Estimate(dest, tier, out, back, breakdown, total, not excluded, excluded, hours, transit)


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
    genre_relaxed: bool                   # ジャンル条件をゆるめたか
    scope_count: int                      # 範囲（国内/海外）内の行き先数


def _genre_ok(dest: dict, wanted: list[str], min_strength: int) -> bool:
    return any(dest["genres"].get(g, 0) >= min_strength for g in wanted)


def search(destinations: list[dict], cond: Conditions) -> Search:
    """条件で絞り込み、スコア順の候補を返す。"""
    in_scope = [
        d for d in destinations
        if d["id"] not in cond.exclude_ids
        and (cond.scope == "both"
             or (cond.scope == "domestic") == (d["region"] != "overseas"))
    ]
    estimates = [estimate(d, cond) for d in in_scope]
    feasible = [e for e in estimates if e.feasible]
    excluded = [e for e in estimates if not e.feasible]

    genre_relaxed = False
    if cond.genres and cond.surprise <= 3:
        strict = [e for e in feasible if _genre_ok(e.dest, cond.genres, 2)]
        if not strict:
            strict = [e for e in feasible if _genre_ok(e.dest, cond.genres, 1)]
        if strict:
            feasible = strict
        elif feasible:
            genre_relaxed = True

    candidates = []
    for e in feasible:
        parts = score_destination(e, cond)
        candidates.append(Candidate(e, parts, total_score(parts)))
    candidates.sort(key=lambda c: c.score, reverse=True)
    return Search(candidates, excluded, genre_relaxed, len(in_scope))


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
    """予算だけが理由で外れた行き先のうち、あといくらで届くかが最小のもの。"""
    only_budget = [e for e in excluded
                   if len(e.reasons_excluded) == 1 and e.reasons_excluded[0].startswith("予算オーバー")]
    if not only_budget:
        return None
    e = min(only_budget, key=lambda e: e.total)
    return e.total - cond.budget_total, e.dest


def explain(cand: Candidate, cond: Conditions, total: int | None = None) -> list[str]:
    """この行き先が選ばれた理由（人が読める形）。"""
    d = cand.dest
    reasons = []
    if cond.genres:
        hits = [GENRES[g] for g in cond.genres if d["genres"].get(g, 0) >= 2]
        if hits:
            reasons.append(f"希望ジャンルのうち「{'・'.join(hits)}」が強い")
    else:
        top = sorted(d["genres"].items(), key=lambda kv: -kv[1])[:2]
        reasons.append(f"ジャンルおまかせ → 「{'・'.join(GENRES[g] for g, _ in top)}」が持ち味の場所")
    diff = d["niche"] - cond.niche
    label = NICHE_LABELS[d["niche"]]
    if diff == 0:
        reasons.append(f"王道〜ニッチの好み（{NICHE_LABELS[cond.niche]}）にぴったり")
    else:
        direction = "ニッチ寄り" if diff > 0 else "王道寄り"
        reasons.append(f"好みより少し{direction}の「{label}」（サプライズ枠）")
    if cond.trip_months() & set(d["best_months"]):
        reasons.append("旅行する月がベストシーズン")
    fit = d["fit"][cond.relation]
    if fit >= 3:
        reasons.append(f"{RELATIONS[cond.relation]}との相性がとても良い")
    elif fit <= 1:
        reasons.append(f"{RELATIONS[cond.relation]}向けの定番ではない（意外性枠）")
    total = cand.est.total if total is None else total
    usage = total / cond.budget_total * 100 if cond.budget_total else 0
    reasons.append(f"概算で予算の {usage:.0f}% に収まる")
    return reasons
