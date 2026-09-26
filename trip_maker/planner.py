"""選ばれた行き先から、日ごとの旅程（時間割・食事・宿・費用）を組み立てる。

旅程は常にいちばん細かい粒度（時刻入り）で作り、決め込み度に応じて
render.py が見せる範囲を変える。こうしておくと決め込み度を動かしても
同じ旅のまま表示の細かさだけが変わる。
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import engine
from .constants import GENRES, LODGING_MEALS_LABELS, LODGING_TIERS, NICHE_LABELS
from .engine import Candidate, Conditions

# ── 1 日の時間の使い方（分） ────────────────────────────────────────
DAY_START = 9 * 60
DAY_END = 18 * 60
DINNER_START = 18 * 60 + 30
DINNER_MIN = 90
NIGHT_START = 20 * 60 + 15
HOME_BY = 21 * 60
BREAKFAST_START = 7 * 60 + 30
LUNCH_EARLIEST = 11 * 60 + 30
LUNCH_LATEST = 14 * 60
LUNCH_MIN = 60
MOVE_SAME_AREA = 20
MOVE_OTHER_AREA = 45

PACE_USE = {"relaxed": 0.65, "normal": 0.8, "packed": 1.0}
PACE_MAX_SPOTS = {"relaxed": 2, "normal": 4, "packed": 6}   # 観光に丸 1 日（7 時間）使える日の上限
FULL_DAY_CAPACITY = 7 * 60
EVENING_START = 16 * 60
SPOT_NOISE = {1: 0.04, 2: 0.08, 3: 0.12, 4: 0.18, 5: 0.3}
TIME_ORDER = {"morning": 0, "day": 1, "evening": 2, "night": 3}

GENRE_TITLE_WORDS = {
    "onsen": "湯けむりに沈む", "gourmet": "食べ尽くす", "nature": "絶景を浴びる",
    "history": "時をさかのぼる", "art": "アートに浸る", "activity": "体ごと遊ぶ",
    "town": "路地をさまよう", "beach": "海にとける", "remote": "地の果てへ行く",
    "drink": "夜を味わう",
}

MISSIONS_COMMON = [
    "地元の人におすすめの店を 1 軒だけ聞いて、そこへ行く",
    "ガイドブックに載っていない路地を 1 本歩いてみる",
    "その土地のスーパーか道の駅で、見たことのない食材を 1 つ買う",
    "今日いちばん良かった景色を 1 枚だけ撮る（撮り直し禁止）",
    "ご当地の飲み物を 1 本試す",
    "旅の同行者（または自分）に今日のベスト 3 を発表する",
    "地元の銭湯・共同浴場・足湯のどれかに入る",
    "ポストカードを 1 枚買って、未来の自分に送る",
    "地図アプリを見ずに 15 分だけ散歩する",
    "朝いちばんに外へ出て、観光客がいない景色を見る",
]
MISSIONS_BY_GENRE = {
    "onsen": ["湯上がりに地元の牛乳かサイダーを飲む", "泉質を宿の人に聞いてみる"],
    "gourmet": ["同じ名物を 2 軒で食べ比べる", "市場で朝ごはんを食べる"],
    "nature": ["スマホを置いて 5 分だけ景色を眺める", "日の出か日の入りを見る"],
    "history": ["御朱印か記念スタンプを 1 つ集める", "由来の看板を 1 つ最後まで読む"],
    "art": ["いちばん気になった作品の前で 3 分立ち止まる", "作品について同行者と感想を言い合う"],
    "activity": ["新しい体験を 1 つ予約なしで探してみる"],
    "town": ["商店街で 500 円以内のおみやげを探す", "喫茶店のモーニングを頼む"],
    "beach": ["海辺で貝殻かシーグラスを 1 つ探す", "夕日の時間に海辺にいる"],
    "remote": ["島（集落）の商店で地元の人と一言話す", "星空を 10 分見上げる"],
    "drink": ["地酒を 1 杯、店の人のおすすめで頼む", "酒蔵か醸造所の試飲をする"],
}


# ════════════════════════════════════════════════════════════════════
# データ構造
# ════════════════════════════════════════════════════════════════════
@dataclass
class Block:
    start: int                 # 0 時からの分（24 時超えは翌日）
    end: int
    kind: str                  # travel / move / spot / meal / lodging / free / snack
    title: str
    detail: str = ""
    cost: int = 0              # グループ合計（円）
    area: str = ""
    spot: dict | None = None
    maps_query: str | None = None


@dataclass
class Day:
    number: int
    date: date
    stop_index: int | None     # 観光する行き先（移動だけの日は None）
    kind: str                  # daytrip / arrival / full / transfer / departure / transit / home
    theme: str = ""
    areas: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    lodging: str | None = None
    rain_plan: list[dict] = field(default_factory=list)
    mission: str | None = None


@dataclass
class Stop:
    dest: dict
    nights: int
    tier: str


@dataclass
class Plan:
    cond: Conditions
    candidate: Candidate
    stops: list[Stop]
    access_out: dict
    access_back: dict
    transfer: dict | None
    days: list[Day]
    costs: dict[str, int]
    total: int
    title: str
    reasons: list[str]
    tier: str
    tier_note: str | None
    highlights: list[dict]
    must_eat: list[dict]
    packing: list[str]
    bookings: list[str]
    over_budget: bool
    dest_seed: int
    plan_seed: int
    alternatives: list[Candidate] = field(default_factory=list)

    @property
    def dest(self) -> dict:
        return self.stops[0].dest

    @property
    def per_person(self) -> int:
        return int(round(self.total / max(1, self.cond.people), -2))

    @property
    def trip_code(self) -> str:
        return f"{self.dest_seed}-{self.plan_seed}"


def fmt_time(minutes: int) -> str:
    minutes = int(minutes)
    day, rest = divmod(minutes, 24 * 60)
    text = f"{rest // 60}:{rest % 60:02d}"
    return f"翌{text}" if day else text


def _round15(minutes: float) -> int:
    return int(math.ceil(minutes / 15) * 15)


def reverse_route(route: str) -> str:
    """「A→（X）→B」を「B→（X）→A」にする（帰路の表示用）。"""
    return "→".join(reversed(route.split("→")))


def maps_url(query: str) -> str:
    from urllib.parse import quote
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


# ════════════════════════════════════════════════════════════════════
# スポットの並べ方
# ════════════════════════════════════════════════════════════════════
def spot_score(spot: dict, cond: Conditions, rng: random.Random) -> float:
    if cond.genres:
        overlap = len(set(spot["genres"]) & set(cond.genres))
        genre = min(1.0, 0.2 + 0.6 * bool(overlap) + 0.2 * max(0, overlap - 1))
    else:
        genre = 0.5
    niche = 1 - abs(spot["niche"] - cond.niche) / 4
    fit = 1.0 if cond.relation in spot.get("fit", []) else 0.5
    return 0.4 * genre + 0.35 * niche + 0.25 * fit + rng.gauss(0, SPOT_NOISE[cond.surprise])


def usable_spots(dest: dict, cond: Conditions, months: set[int]) -> list[dict]:
    out = []
    for s in dest["spots"]:
        if cond.relation in s.get("avoid", []):
            continue
        if "months" in s and not (months & set(s["months"])):
            continue
        out.append(s)
    return out


def is_night_spot(s: dict) -> bool:
    return "night" in s["when"] and not ({"morning", "day"} & set(s["when"]))


def _time_key(s: dict) -> int:
    return min(TIME_ORDER[w] for w in s["when"])


def is_open(s: dict, day: date) -> bool:
    """定休日（closed: 0=月〜6=日）でなければ True。"""
    return day.weekday() not in s.get("closed", [])


def lodging_label(lo: dict) -> str:
    """宿のタイプに食事条件を添える（タイプ名にすでに含まれていれば重ねない）。"""
    if re.search(r"素泊|朝食|[2二]食|夕食", lo["type"]):
        return lo["type"]
    return f"{lo['type']}（{LODGING_MEALS_LABELS[lo['meals']]}）"


def choose_day_spots(ranked: list[tuple[float, dict]], used: set[str], capacity_min: int,
                     pace: str, allow_evening: bool, day: date | None = None) -> list[dict]:
    """1 日ぶんのスポットを選ぶ。最上位スポットのエリアを中心に、移動時間込みで詰める。"""
    max_spots = max(1, round(PACE_MAX_SPOTS[pace] * min(1.0, capacity_min / FULL_DAY_CAPACITY)))
    budget = capacity_min * PACE_USE[pace]
    pool = [(sc, s) for sc, s in ranked if s["name"] not in used and not is_night_spot(s)
            and (allow_evening or set(s["when"]) - {"evening", "night"})
            and (day is None or is_open(s, day))]
    chosen: list[dict] = []
    spent = 0.0
    primary = None
    other_area_used = False
    for sc, s in sorted(pool, key=lambda x: -x[0]):
        if len(chosen) >= max_spots:
            break
        dur = s["hours"] * 60
        if primary is None:
            move = MOVE_SAME_AREA
        elif s["area"] == primary or (other_area_used and s["area"] in {c["area"] for c in chosen}):
            move = MOVE_SAME_AREA
        elif other_area_used:
            continue
        else:
            move = MOVE_OTHER_AREA
        if spent + dur + move > budget and chosen:
            continue
        if spent + dur + move > capacity_min:
            continue
        if primary is not None and s["area"] != primary:
            other_area_used = True
        primary = primary or s["area"]
        chosen.append(s)
        spent += dur + move
    area_rank = {primary: 0}
    return sorted(chosen, key=lambda s: (area_rank.get(s["area"], 1), _time_key(s)))


# ════════════════════════════════════════════════════════════════════
# 日程の骨組み
# ════════════════════════════════════════════════════════════════════
@dataclass
class _DaySkeleton:
    kind: str
    stop: int | None           # 観光する行き先
    start: int | None          # 観光を始められる時刻
    end: int | None            # 観光を切り上げる時刻
    night_stop: int | None     # この夜に泊まる行き先（None は宿泊なし）
    depart_home: int | None = None
    arrive_home: int | None = None
    arrive_dest: int | None = None
    transfer_from: int | None = None
    transit_depart: int | None = None
    transit_arrive: int | None = None


def _out_times(opt: dict, tz: float = 0) -> tuple[int, int]:
    """往路の出発時刻（日本時間）と到着時刻（現地時間）。夜行の場合の到着は翌日の時刻。

    tz は現地時間と日本時間の差（時間）。日付変更線をまたぐ行き先（ハワイなど）は
    朝に出ると現地の前日に着いてしまうため、夜に出て同じ日付の昼に着く便を想定する。
    """
    hours, shift = opt["hours"], int(tz * 60)
    if opt.get("overnight"):
        depart = 11 * 60 if hours >= 16 else 22 * 60
        arrive = max(6 * 60, min(16 * 60, depart + int(hours * 60) + shift - 24 * 60))
        return depart, arrive
    depart = 8 * 60 if hours <= 3 else 7 * 60
    if depart + hours * 60 + shift < 6 * 60:
        depart = 21 * 60
    return depart, _round15(depart + hours * 60 + shift)


def _back_times(opt: dict, tz: float = 0) -> tuple[int, int]:
    """復路の出発時刻（現地時間）と帰着時刻（日本時間。24 時超えは翌日）。"""
    hours, shift = opt["hours"], int(tz * 60)
    if opt.get("overnight"):
        depart = 14 * 60 if hours >= 16 else 21 * 60
    else:
        latest = HOME_BY + shift - hours * 60
        if latest < 9 * 60 and tz <= -5:   # 日付変更線をまたいで翌日に帰着する便
            latest += 24 * 60
        depart = max(9 * 60, int(latest // 15 * 15))
    return depart, depart - shift + int(hours * 60)


def build_skeleton(cond: Conditions, out: dict, back: dict, night_stops: list[int | None],
                   tz_out: float = 0, tz_back: float = 0) -> list[_DaySkeleton]:
    n = cond.nights
    days: list[_DaySkeleton] = []
    out_dep, out_arr = _out_times(out, tz_out)
    back_dep, back_arr = _back_times(back, tz_back)

    for k in range(n + 1):
        night = night_stops[k] if k < n else None
        prev = night_stops[k - 1] if k >= 1 else None
        if n == 0:
            end = back_dep - 30
            days.append(_DaySkeleton("daytrip", 0, out_arr + 15, end, None,
                                     depart_home=out_dep, arrive_dest=out_arr, arrive_home=back_arr))
            continue
        if k == 0 and out.get("overnight"):
            days.append(_DaySkeleton("transit", None, None, None, None, transit_depart=out_dep))
            continue
        if k == n and back.get("overnight"):
            days.append(_DaySkeleton("home", None, None, None, None, arrive_home=back_arr - 24 * 60))
            continue
        first_day = k == 0 or (k == 1 and out.get("overnight"))
        if first_day:
            stop = night if night is not None else 0
            days.append(_DaySkeleton("arrival", stop, out_arr + 15, DAY_END, night,
                                     depart_home=None if out.get("overnight") else out_dep,
                                     arrive_dest=out_arr))
            continue
        if k == n or (k == n - 1 and back.get("overnight")):
            stop = prev if prev is not None else night_stops[-1]
            sk = _DaySkeleton("departure", stop, DAY_START, back_dep - 30, None)
            if back.get("overnight"):
                sk.transit_depart = back_dep
            else:
                sk.arrive_home = back_arr
            days.append(sk)
            continue
        if prev is not None and night is not None and prev != night:
            days.append(_DaySkeleton("transfer", night, None, DAY_END, night, transfer_from=prev))
            continue
        days.append(_DaySkeleton("full", night if night is not None else prev, DAY_START, DAY_END, night))
    return days


# ════════════════════════════════════════════════════════════════════
# 旅程の組み立て
# ════════════════════════════════════════════════════════════════════
DRINK_RE = re.compile(r"地酒|日本酒|焼酎|ビール|ワイン|ウイスキー|泡盛|般若湯|マッコリ|樽酒|どぶろく|ハイボール|シードル")


def is_drink(food: dict) -> bool:
    """酒類かどうか（データの "drink" 指定があればそれを優先）。酒類は食事の主役にせず夕食に添える。"""
    if "drink" in food:
        return bool(food["drink"])
    return bool(DRINK_RE.search(food["name"])) and "甘酒" not in food["name"]


def _foods_by_slot(dest: dict) -> dict[str, list[dict]]:
    pools = {slot: [f for f in dest["foods"] if f["meal"] == slot and not is_drink(f)]
             for slot in ("breakfast", "lunch", "dinner", "snack")}
    pools["drink"] = [f for f in dest["foods"] if is_drink(f)]
    return pools


def _add_drink(block: Block, foods_left: dict[str, list[dict]], cond: Conditions, rng: random.Random) -> None:
    """夕食に地酒などを 1 杯添える（お酒ジャンル選択時は必ず、それ以外は半々）。大人の人数ぶん加算。"""
    drinks = foods_left.get("drink") or []
    if not drinks or ("drink" not in cond.genres and rng.random() < 0.5):
        return
    drink = drinks.pop(rng.randrange(len(drinks)))
    block.title += f"（＋{drink['name']}）"
    block.cost += int(round(drink["price"] * cond.adults, -1))
    if drink.get("note"):
        block.detail = f"{block.detail} ／ {drink['note']}" if block.detail else drink["note"]


def _meal_block(start: int, minutes: int, slot: str, dest: dict, tier: str, cond: Conditions,
                foods_left: dict[str, list[dict]], rng: random.Random, at_lodging: bool = False) -> Block:
    label = {"breakfast": "朝食", "lunch": "昼食", "dinner": "夕食"}[slot]
    if at_lodging:
        return Block(start, start + minutes, "meal", f"{label}（宿）",
                     f"宿の{LODGING_MEALS_LABELS[dest['lodging'][tier]['meals']]}プランに含まれる",
                     0)
    options = foods_left.get(slot) or []
    base = engine.meals_per_day_cost(dest, tier)[slot]
    if options:
        food = options.pop(rng.randrange(len(options)))
        # 名物の価格を基本に、宿の段階（贅沢度）で少しだけ上下させる
        price = food["price"] * (0.85 if tier == "budget" else 1.3 if tier == "premium" else 1.0)
        cost = int(round(price * engine.units(cond.adults, cond.kids, "food"), -1))
        return Block(start, start + minutes, "meal", f"{label}：{food['name']}", food.get("note", ""),
                     cost, maps_query=f"{food['name']} {dest['name'].split('・')[0]}")
    generic = {"breakfast": "カフェやパン屋で朝ごはん", "lunch": "地元の食堂でランチ",
               "dinner": "地元の居酒屋・食堂で夕食"}[slot]
    return Block(start, start + minutes, "meal", f"{label}：{generic}", "",
                 int(round(base * engine.units(cond.adults, cond.kids, "food"), -1)))


def _spot_block(start: int, s: dict, dest: dict, cond: Conditions) -> Block:
    dur = int(s["hours"] * 60)
    cost = int(round(s["cost"] * engine.units(cond.adults, cond.kids, "spot"), -1))
    q = f"{s['name']} {dest['pref'] if dest['region'] != 'overseas' else dest['name']}"
    return Block(start, start + dur, "spot", s["name"], s["note"], cost, s["area"], s, q)


def _layout_sightseeing(day: Day, spots: list[dict], start: int, end: int, dest: dict, tier: str,
                        cond: Conditions, foods_left, rng, first_move: bool) -> None:
    """観光枠の中にスポットと昼食を並べる。"""
    t = start
    lunch_done = start > LUNCH_LATEST - LUNCH_MIN
    prev_area = None
    for i, s in enumerate(spots):
        move = 0
        if i > 0 or first_move:
            move = MOVE_SAME_AREA if (prev_area in (None, s["area"])) else MOVE_OTHER_AREA
        if not lunch_done and t + move >= LUNCH_EARLIEST:
            day.blocks.append(_meal_block(t, LUNCH_MIN, "lunch", dest, tier, cond, foods_left, rng))
            t += LUNCH_MIN
            lunch_done = True
        dur = int(s["hours"] * 60)
        earliest = EVENING_START if not ({"morning", "day"} & set(s["when"])) else 0
        if t + move < earliest and earliest + dur <= end:
            gap_start = t
            t = earliest - move
            if t - gap_start >= 30:
                day.blocks.append(Block(gap_start, t, "free", "自由時間",
                                        "カフェで休む・気になった店に戻る・宿に荷物を置く"))
        if t + move + dur > end:
            continue
        if move:
            label = "移動" if prev_area in (None, s["area"]) else f"移動（{s['area']}へ）"
            day.blocks.append(Block(t, t + move, "move", label))
        t += move
        day.blocks.append(_spot_block(t, s, dest, cond))
        t += dur
        prev_area = s["area"]
    if not lunch_done and max(t, 12 * 60) + LUNCH_MIN <= end and t <= LUNCH_LATEST:
        if 12 * 60 - t >= 60:
            day.blocks.append(Block(t, 12 * 60, "free", "自由時間・散策",
                                    "宿の周りを歩く・カフェで休む・おみやげを見る"))
        day.blocks.append(_meal_block(max(t, 12 * 60), LUNCH_MIN, "lunch", dest, tier, cond, foods_left, rng))
        t = max(t, 12 * 60) + LUNCH_MIN
    if end - t >= 60:
        snack = foods_left.get("snack") or []
        if snack:
            food = snack.pop(rng.randrange(len(snack)))
            cost = int(round(food["price"] * engine.units(cond.adults, cond.kids, "food"), -1))
            day.blocks.append(Block(t, t + 30, "snack", f"おやつ：{food['name']}", food.get("note", ""),
                                    cost, maps_query=f"{food['name']} {dest['name'].split('・')[0]}"))
            t += 30
        if end - t >= 60:
            if day.kind in ("departure", "daytrip"):
                day.blocks.append(Block(t, end, "free", "自由時間・おみやげ探し",
                                        "駅や空港へ向かう前に、名物やおみやげを買う"))
            else:
                day.blocks.append(Block(t, end, "free", "自由時間",
                                        "気になった店に戻る・カフェで休む・宿で早めにくつろぐ"))


def _theme(day: Day, dest: dict) -> str:
    spots = [b.spot for b in day.blocks if b.spot]
    if not spots:
        return {"transit": "夜行で出発", "home": "帰着"}.get(day.kind, "のんびり過ごす日")
    counts: dict[str, int] = {}
    for s in spots:
        for g in s["genres"]:
            counts[g] = counts.get(g, 0) + 1
    genre = GENRES[max(counts, key=counts.get)]
    area = day.areas[0] if day.areas else dest["name"]
    prefix = {"arrival": "到着して", "departure": "最後に", "transfer": "移動して",
              "daytrip": ""}.get(day.kind, "")
    return f"{prefix}{area}で{genre}"


def _rain_plan(dest: dict, day_spots: list[dict], all_used: set[str], cond: Conditions, months,
               day: date) -> list[dict]:
    if not day_spots or all(s["indoor"] for s in day_spots):
        return []
    areas = {s["area"] for s in day_spots}
    indoor = [s for s in usable_spots(dest, cond, months) if s["indoor"] and s not in day_spots and is_open(s, day)]
    indoor.sort(key=lambda s: (s["area"] not in areas, s["name"] in all_used))
    return indoor[:2]


def _choose_second_stop(cand: Candidate, destinations: list[dict], cond: Conditions,
                        rng: random.Random) -> tuple[dict, dict] | None:
    dest = cand.dest
    nights = cond.nights
    if cond.multi_stop == "off" or not dest.get("nearby"):
        return None
    if cond.multi_stop == "auto" and not (nights >= 3 and nights > dest["ideal_nights"][1] + 1):
        return None
    if cond.multi_stop == "on" and nights < 2:
        return None
    by_id = {d["id"]: d for d in destinations}
    months = cond.trip_months()
    options = []
    for link in dest["nearby"]:
        d2 = by_id.get(link["id"])
        if not d2 or d2["id"] in cond.exclude_ids:
            continue
        if months & set(d2["avoid_months"]):
            continue
        if engine.choose_access(d2["access"].get(cond.hub, []), cond, cond.end_date) is None:
            continue
        w = 0.2 + engine.genre_score(d2["genres"], cond.genres) + engine.niche_score(d2["niche"], cond.niche)
        options.append((w, d2, link))
    if not options:
        return None
    _, d2, link = rng.choices(options, weights=[o[0] for o in options], k=1)[0]
    return d2, link


def _assign_nights(cond: Conditions, out: dict, back: dict, stops: list[dict]) -> list[int | None] | None:
    """各夜にどの行き先で泊まるか（None は夜行移動中）。"""
    n = cond.nights
    slots = list(range(n))
    transit = set()
    if out.get("overnight") and n:
        transit.add(0)
    if back.get("overnight") and n:
        transit.add(n - 1)
    lodging_nights = [k for k in slots if k not in transit]
    result: list[int | None] = [None] * n
    if len(stops) == 1:
        for k in lodging_nights:
            result[k] = 0
        return result
    d1, d2 = stops
    need2 = max(1, d2["min_nights"])
    n1 = min(max(1, d1["ideal_nights"][1]), len(lodging_nights) - need2)
    if n1 < max(1, d1["min_nights"]):
        return None
    for i, k in enumerate(lodging_nights):
        result[k] = 0 if i < n1 else 1
    return result


def build_plan(cand: Candidate, cond: Conditions, destinations: list[dict], dest_seed: int,
               plan_seed: int, tier_override: str | None = None, allow_multi: bool = True) -> Plan:
    rng = random.Random(f"plan-{plan_seed}")
    dest = cand.dest
    est = cand.est if tier_override is None else engine.estimate(dest, cond, tier_override)
    tier = est.tier
    months = cond.trip_months()

    # ── 周遊（2 か所めぐり） ──
    stops_d = [dest]
    transfer = None
    second = _choose_second_stop(cand, destinations, cond, rng) if allow_multi else None
    out = est.access_out
    back = est.access_back
    night_stops = None
    if second:
        d2, link = second
        back2 = engine.choose_access(d2["access"][cond.hub], cond, cond.end_date)
        ns = _assign_nights(cond, out, back2, [dest, d2])
        if ns is not None:
            stops_d, transfer, back, night_stops = [dest, d2], link, back2, ns
    if night_stops is None:
        night_stops = _assign_nights(cond, out, back, [dest])

    stops = [Stop(d, sum(1 for s in night_stops if s == i), tier) for i, d in enumerate(stops_d)]
    tz_out, tz_back = stops_d[0].get("tz_offset", 0), stops_d[-1].get("tz_offset", 0)
    skeleton = build_skeleton(cond, out, back, night_stops, tz_out, tz_back)

    # ── スポットの順位づけ（行き先ごと） ──
    ranked = {i: sorted(((spot_score(s, cond, rng), s) for s in usable_spots(d, cond, months)),
                        key=lambda x: -x[0]) for i, d in enumerate(stops_d)}
    foods_left = {i: _foods_by_slot(d) for i, d in enumerate(stops_d)}
    used: set[str] = set()
    nights_used_for_night_spot = 0

    days: list[Day] = []
    for k, sk in enumerate(skeleton):
        day_date = cond.start_date + timedelta(days=k)
        day = Day(k + 1, day_date, sk.stop, sk.kind)
        d = stops_d[sk.stop] if sk.stop is not None else dest
        dtier = tier

        if sk.kind == "transit":
            day.blocks.append(Block(sk.transit_depart, sk.transit_depart + int(out["hours"] * 60), "travel",
                                    f"出発：{out['route']}", "夜行（車中・船中泊）",
                                    engine.access_cost(out, cond, cond.start_date)))
            day.theme = _theme(day, d)
            days.append(day)
            continue
        if sk.kind == "home":
            day.blocks.append(Block(max(0, sk.arrive_home - 30), sk.arrive_home, "travel", "帰着",
                                    reverse_route(back["route"])))
            day.theme = _theme(day, d)
            days.append(day)
            continue

        # 朝食（前夜に泊まっている場合）
        prev_night = night_stops[k - 1] if k >= 1 and k - 1 < len(night_stops) else None
        if prev_night is not None:
            pd = stops_d[prev_night]
            at_lodging = pd["lodging"][dtier]["meals"] >= 1
            day.blocks.append(_meal_block(BREAKFAST_START, 45, "breakfast", pd, dtier, cond,
                                          foods_left[prev_night], rng, at_lodging=at_lodging))

        start, end = sk.start, sk.end
        first_move = True
        if sk.kind in ("arrival", "daytrip"):
            if sk.depart_home is not None and tz_out:
                day.blocks.append(Block(sk.arrive_dest, sk.arrive_dest, "travel", f"移動：{out['route']}",
                                        f"日本時間 {fmt_time(sk.depart_home)} 発 → 現地時間 {fmt_time(sk.arrive_dest)} 着"
                                        f"（時差 {tz_out:+g} 時間・所要 約{out['hours']:.1f} 時間）",
                                        engine.access_cost(out, cond, cond.start_date)))
            elif sk.depart_home is not None:
                day.blocks.append(Block(sk.depart_home, sk.arrive_dest, "travel",
                                        f"移動：{out['route']}", f"片道 約{out['hours']:.1f} 時間",
                                        engine.access_cost(out, cond, cond.start_date)))
            else:
                day.blocks.append(Block(sk.arrive_dest, sk.arrive_dest, "travel", f"到着：{d['name']}",
                                        out["route"]))
            if sk.arrive_dest > LUNCH_LATEST - LUNCH_MIN and sk.depart_home is not None:
                day.blocks.append(Block(sk.arrive_dest - 30, sk.arrive_dest, "meal", "昼食：移動中に駅弁・空港グルメ", "",
                                        int(round(engine.meals_per_day_cost(d, dtier)["lunch"]
                                                  * engine.units(cond.adults, cond.kids, "food"), -1))))
                day.blocks.sort(key=lambda b: b.start)
            first_move = True
        if sk.kind == "transfer":
            from_d = stops_d[sk.transfer_from]
            dep = 10 * 60
            arr = _round15(dep + transfer["hours"] * 60)
            cost = int(round(transfer["cost"] * engine.units(cond.adults, cond.kids, "rail"), -1))
            day.blocks.append(Block(dep, arr, "travel", f"移動：{transfer['route']}",
                                    f"{from_d['name']} → {d['name']}（約{transfer['hours']:.1f} 時間）", cost))
            start = arr + 15

        if sk.night_stop is not None and end is not None:
            if stops_d[sk.night_stop]["lodging"][dtier]["meals"] >= 2:
                end = min(end, 16 * 60 + 45)
        if start is not None and end is not None and end - start >= 45:
            capacity = end - start
            if start < LUNCH_LATEST and end > LUNCH_EARLIEST:
                capacity -= LUNCH_MIN
            allow_evening = sk.kind not in ("departure", "daytrip") or end >= 17 * 60
            spots = choose_day_spots(ranked[sk.stop], used, max(0, capacity), cond.pace, allow_evening, day_date)
            used.update(s["name"] for s in spots)
            day.areas = list(dict.fromkeys(s["area"] for s in spots))
            _layout_sightseeing(day, spots, start, end, d, dtier, cond, foods_left[sk.stop], rng, first_move)
            day.rain_plan = [s for s in _rain_plan(d, spots, used, cond, months, day_date)]

        # 夜：宿・夕食・夜のスポット
        if sk.night_stop is not None:
            nd = stops_d[sk.night_stop]
            lo = nd["lodging"][dtier]
            day.lodging = lodging_label(lo)
            checkin = 17 * 60 if lo["meals"] >= 2 else DAY_END
            day.blocks.append(Block(checkin, checkin + 30, "lodging", f"チェックイン：{lo['type']}",
                                    f"{nd['name']}泊・{LODGING_MEALS_LABELS[lo['meals']]}"))
            dinner = _meal_block(DINNER_START, DINNER_MIN, "dinner", nd, dtier, cond,
                                 foods_left[sk.night_stop], rng, at_lodging=lo["meals"] >= 2)
            _add_drink(dinner, foods_left[sk.night_stop], cond, rng)
            day.blocks.append(dinner)
            night_ok = cond.pace != "relaxed" or rng.random() < 0.5
            if night_ok:
                night_pool = [s for _, s in ranked[sk.night_stop] if "night" in s["when"] and s["name"] not in used
                              and is_open(s, day_date)
                              and (cond.relation != "family_kids" or "family_kids" in s.get("fit", []))]
                if night_pool:
                    s = night_pool[0]
                    used.add(s["name"])
                    nights_used_for_night_spot += 1
                    day.blocks.append(Block(NIGHT_START - 15, NIGHT_START, "move", "移動"))
                    day.blocks.append(_spot_block(NIGHT_START, s, nd, cond))

        # 帰路
        if sk.kind in ("departure", "daytrip"):
            back_dep = sk.end + 30
            had_lunch = any(b.title.startswith("昼食") for b in day.blocks)
            on_the_way = None
            if back_dep >= 17 * 60 and sk.transit_depart is None:
                on_the_way = "夕食：帰りの車内で駅弁・空港グルメ"
            elif 11 * 60 <= back_dep <= 15 * 60 and not had_lunch:
                on_the_way = "昼食：駅・空港で"
            if on_the_way:
                day.blocks.append(Block(back_dep, back_dep + 30, "meal", on_the_way, "",
                                        int(round(engine.meals_per_day_cost(d, dtier)["lunch"]
                                                  * engine.units(cond.adults, cond.kids, "food"), -1))))
            back_cost = engine.access_cost(back, cond, cond.end_date)
            if sk.transit_depart is not None:
                day.blocks.append(Block(sk.transit_depart, sk.transit_depart + int(back["hours"] * 60), "travel",
                                        f"帰路：{reverse_route(back['route'])}", "夜行（車中・船中泊）", back_cost))
            elif tz_back:
                day.blocks.append(Block(back_dep, back_dep, "travel", f"帰路：{reverse_route(back['route'])}",
                                        f"現地時間 {fmt_time(back_dep)} 発 → 日本時間 {fmt_time(sk.arrive_home)} 着"
                                        f"（所要 約{back['hours']:.1f} 時間）", back_cost))
            else:
                day.blocks.append(Block(back_dep, sk.arrive_home, "travel", f"帰路：{reverse_route(back['route'])}",
                                        f"片道 約{back['hours']:.1f} 時間", back_cost))

        day.blocks.sort(key=lambda b: (b.start, b.kind == "travel" and b.start > 12 * 60, b.end))
        day.theme = _theme(day, d)
        days.append(day)

    # ── 費用 ──
    transport = engine.access_cost(out, cond, cond.start_date) + engine.access_cost(back, cond, cond.end_date)
    if transfer:
        transport += int(round(transfer["cost"] * engine.units(cond.adults, cond.kids, "rail"), -1))
    lodging_total = 0
    for i, st in enumerate(stops):
        nights_dates = [cond.start_date + timedelta(days=k) for k, s in enumerate(night_stops) if s == i]
        if nights_dates:
            lodging_total += engine.lodging_cost(st.dest, tier, cond, nights_dates)
    food = sum(b.cost for day in days for b in day.blocks if b.kind in ("meal", "snack"))
    activities = sum(b.cost for day in days for b in day.blocks if b.kind == "spot")
    local = 0
    for i, st in enumerate(stops):
        stop_days = sum(1 for day in days if day.stop_index == i)
        local += engine.local_transport_cost(st.dest, cond, stop_days)
    costs = {"transport": transport, "lodging": lodging_total, "food": food,
             "local": local, "activities": activities}
    total = sum(costs.values())

    # ── 仕上げ ──
    all_spots = [b.spot for day in days for b in day.blocks if b.spot]
    score_of = {s["name"]: sc for i in ranked for sc, s in ranked[i]}
    highlights = sorted(all_spots, key=lambda s: -score_of.get(s["name"], 0))[:5]
    must_eat = _must_eat(stops_d, days)
    return Plan(
        cond=cond, candidate=cand, stops=stops, access_out=out, access_back=back, transfer=transfer,
        days=days, costs=costs, total=total, title=make_title(stops_d, cond, rng), reasons=engine.explain(cand, cond, total),
        tier=tier, tier_note=None, highlights=highlights, must_eat=must_eat,
        packing=packing_list(stops_d, cond, out, back), bookings=booking_list(stops_d, out, back, all_spots, tier),
        over_budget=total > cond.budget_total, dest_seed=dest_seed, plan_seed=plan_seed,
    )


def plan_within_budget(cand: Candidate, cond: Conditions, destinations: list[dict],
                       dest_seed: int, plan_seed: int) -> Plan:
    """予算を超えたら、宿の段階を下げて組み直す（宿おまかせのときのみ）。"""
    first = build_plan(cand, cond, destinations, dest_seed, plan_seed)
    if not first.over_budget:
        return first
    tiers = ["premium", "standard", "budget"]
    plan = first
    for allow_multi in ([True, False] if len(first.stops) > 1 else [True]):
        for tier in tiers[tiers.index(first.tier):]:
            if allow_multi and tier == first.tier:
                continue
            retry = build_plan(cand, cond, destinations, dest_seed, plan_seed, tier_override=tier,
                               allow_multi=allow_multi)
            notes = []
            if tier != first.tier:
                notes.append(f"宿を「{LODGING_TIERS[tier]}」の段階に")
            if not allow_multi:
                notes.append("周遊をやめて 1 か所に")
            retry.tier_note = f"予算に収めるため、{'、'.join(notes)}しました"
            if not retry.over_budget:
                return retry
            plan = retry
    return plan


# ════════════════════════════════════════════════════════════════════
# タイトル・食・持ち物・予約
# ════════════════════════════════════════════════════════════════════
def make_title(stops: list[dict], cond: Conditions, rng: random.Random) -> str:
    dest = stops[0]
    genres = [g for g in cond.genres if dest["genres"].get(g, 0) >= 2]
    if not genres:
        genres = [g for g, v in sorted(dest["genres"].items(), key=lambda kv: -kv[1]) if v == max(dest["genres"].values())]
    g = rng.choice(genres)
    name = "・".join(s["name"] for s in stops) if len(stops) > 1 else dest["name"]
    span = "日帰り" if cond.nights == 0 else f"{cond.nights}泊{cond.days}日"
    return f"【{NICHE_LABELS[dest['niche']]}×{GENRES[g]}】{name}で{GENRE_TITLE_WORDS[g]}{span}"


def _must_eat(stops: list[dict], days: list[Day]) -> list[dict]:
    eaten = {b.title.split("：", 1)[-1] for day in days for b in day.blocks if b.kind in ("meal", "snack")}
    foods = [f for d in stops for f in d["foods"]]
    planned = [f for f in foods if f["name"] in eaten]
    rest = [f for f in foods if f["name"] not in eaten]
    return (planned + rest)[:4]


def _uses_ship(*options: dict) -> bool:
    return any(o["mode"] == "ferry" or "船" in o["route"] or "フェリー" in o["route"] for o in options)


def packing_list(stops: list[dict], cond: Conditions, out: dict, back: dict) -> list[str]:
    items = ["スマホの充電器・モバイルバッテリー", "常備薬", "着替え（泊数ぶん）"]
    genres = {g for d in stops for g, v in d["genres"].items() if v >= 2}
    months = cond.trip_months()
    overseas = any(d["region"] == "overseas" for d in stops)
    if overseas:
        items += ["パスポート（残存期間を確認）", "変換プラグ", "海外で使えるクレジットカード", "eSIM・Wi-Fiルーター"]
    if any(d["local_transport"]["car"] for d in stops):
        items.append("運転免許証")
    if "beach" in genres and months & {5, 6, 7, 8, 9, 10}:
        items += ["水着・ラッシュガード", "日焼け止め", "サンダル"]
    if genres & {"nature", "activity", "remote"}:
        items += ["歩きやすい靴", "レインウェア（折りたたみ傘より両手が空くもの）"]
    if "onsen" in genres:
        items.append("湯上がり用の小さいタオル（宿にあれば不要）")
    if months & {12, 1, 2, 3} and not overseas and not any(d["region"] == "okinawa" for d in stops):
        items += ["防寒着・手袋", "滑りにくい靴（雪国の場合）"]
    if months & {6, 7, 8}:
        items.append("虫よけ・汗ふきシート")
    if any(d["niche"] >= 4 for d in stops):
        items.append("現金（小さな島や集落ではカードが使えない店がある）")
    if _uses_ship(out, back):
        items.append("酔い止め（船に乗る場合）")
    if cond.kids:
        items += ["子どもの着替え・おやつ", "子ども用の常備薬"]
    return list(dict.fromkeys(items))


def booking_list(stops: list[dict], out: dict, back: dict, spots: list[dict], tier: str) -> list[str]:
    todo = []
    modes = {out["mode"], back["mode"]}
    if "flight" in modes:
        todo.append("航空券（早割は早いほど安い。国内線は 2 か月前ごろまでが目安）")
    if "rail" in modes:
        todo.append("新幹線・特急の指定席（1 か月前の 10 時から発売）")
    if _uses_ship(out, back):
        todo.append("フェリー・高速船（便数が少ない航路は早めに。欠航時の予備日も検討）")
    for d in stops:
        todo.append(f"宿：{d['name']}の{d['lodging'][tier]['type']}")
        if d["local_transport"]["car"]:
            todo.append(f"レンタカー：{d['name']}（台数が少ない地域は早めに）")
    for s in spots:
        if s.get("booking"):
            todo.append(f"予約が必要：{s['name']}")
    if any(d["region"] == "overseas" for d in stops):
        todo.append("入国条件の最終確認（ビザ・電子渡航認証・パスポート残存期間）")
    todo.append("旅行直前：営業日・営業時間・料金を公式サイトで最終確認")
    return todo


def add_missions(plan: Plan, rng: random.Random) -> None:
    genres = [g for d in (s.dest for s in plan.stops) for g, v in d["genres"].items() if v >= 2]
    pool = list(MISSIONS_COMMON)
    for g in genres:
        pool += MISSIONS_BY_GENRE.get(g, [])
    rng.shuffle(pool)
    for day in plan.days:
        if day.kind in ("transit", "home") or not pool:
            continue
        day.mission = pool.pop()


def make_plan(cand: Candidate, cond: Conditions, destinations: list[dict], dest_seed: int, plan_seed: int,
              alternatives: list[Candidate] | None = None) -> Plan:
    plan = plan_within_budget(cand, cond, destinations, dest_seed, plan_seed)
    if plan.tier_note is None and cond.lodging_pref not in ("auto", plan.tier):
        plan.tier_note = f"予算の都合で、宿は「{LODGING_TIERS[plan.tier]}」の段階にしました"
    add_missions(plan, random.Random(f"mission-{plan_seed}"))
    plan.alternatives = alternatives or []
    return plan
