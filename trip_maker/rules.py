"""見積もり（engine）と旅程づくり（planner）が共通で使う、時刻・時間帯・分類のルール。

見積もりと旅程で同じルールを使わないと、見積もりでは予算内なのに旅程にすると
予算を超える、といったずれが起きる。ここに置いたものは両方から参照する。
"""

from __future__ import annotations

import math
import re

# ── 1 日の時刻（0 時からの分） ────────────────────────────────────────
DAY_START = 9 * 60
DAY_END = 18 * 60
HOME_BY = 21 * 60
DINNER_BEFORE_RETURN = 19 * 60 + 30   # これ以降に帰路につくなら、帰る前に現地で夕食をとる
ON_BOARD_DINNER_FROM = 17 * 60        # これ以降〜21 時に帰路につくなら、車内・機内で軽く夕食

# スポットの時間帯（when）ごとに、居てよい時間の範囲
TIME_WINDOWS = {
    "morning": (6 * 60, 12 * 60 + 30),
    "day": (8 * 60 + 30, 18 * 60),
    "evening": (16 * 60, 21 * 60),
    "night": (19 * 60, 24 * 60),
}


def round15(minutes: float) -> int:
    return int(math.ceil(minutes / 15) * 15)


def spot_intervals(s: dict) -> list[tuple[int, int]]:
    """スポットを置いてよい時間帯（when の窓を重なり・隣接でつないだもの）。"""
    spans = sorted(TIME_WINDOWS[w] for w in s["when"])
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def fits_time(s: dict, begin: int, end: int) -> bool:
    """[begin, end] がスポットの時間帯のどれか 1 つに収まるか。"""
    return any(a <= begin and end <= b for a, b in spot_intervals(s))


def earliest_begin(s: dict, t: int, dur: int, limit: int) -> int | None:
    """t 以降で、時間帯に収まり limit までに終えられるいちばん早い開始時刻。なければ None。"""
    for a, b in spot_intervals(s):
        begin = max(t, a)
        if begin + dur <= min(b, limit):
            return begin
    return None


# ── 往復の時刻 ─────────────────────────────────────────────────────
def out_times(opt: dict, tz: float = 0) -> tuple[int, int]:
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
    return depart, round15(depart + hours * 60 + shift)


def back_times(opt: dict, tz: float = 0) -> tuple[int, int]:
    """復路の出発時刻（現地時間）と帰着時刻（日本時間。24 時超えは翌日）。"""
    hours, shift = opt["hours"], int(tz * 60)
    if opt.get("overnight"):
        depart = 14 * 60 if hours >= 16 else 21 * 60
    else:
        latest = HOME_BY + shift - hours * 60
        if latest < 9 * 60 and tz <= -5:   # 日付変更線をまたいで翌日に帰着する便
            latest += 24 * 60
        depart = min(21 * 60, max(9 * 60, int(latest // 15 * 15)))
    return depart, depart - shift + int(hours * 60)


# ── 分類 ───────────────────────────────────────────────────────────
DRINK_RE = re.compile(r"地酒|日本酒|焼酎|ビール|ワイン|ウイスキー|泡盛|般若湯|マッコリ|樽酒|どぶろく|ハイボール|シードル")


def is_drink(food: dict) -> bool:
    """酒類かどうか（データの "drink" 指定があればそれを優先）。酒類は食事の主役にせず夕食に添える。"""
    if "drink" in food:
        return bool(food["drink"])
    return bool(DRINK_RE.search(food["name"])) and "甘酒" not in food["name"]


def link_mode(link: dict) -> str:
    """周遊の区間（nearby）の主な交通手段。データに mode がなければ経路の文から判定する。"""
    if link.get("mode"):
        return link["mode"]
    route = link.get("route", "")
    if re.search(r"飛行機|航空|空港|フライト|ヘリ|JAL|ANA|RAC|JTA|Peach|便）", route):
        return "flight"
    if re.search(r"フェリー|船|ジェットフォイル|高速艇|渡船", route):
        return "ferry"
    if re.search(r"バス", route) and not re.search(r"JR|鉄道|線|新幹線|特急|電車", route):
        return "bus"
    if re.search(r"車|レンタカー|ドライブ", route) and not re.search(r"電車|列車", route):
        return "car"
    return "rail"


def in_scope(dest: dict, scope: str) -> bool:
    return scope == "both" or (scope == "domestic") == (dest["region"] != "overseas")
