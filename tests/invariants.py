"""旅程が満たすべき性質のチェック（テストと調査スクリプトの両方で使う）。"""

from trip_maker import planner
from trip_maker.planner import (
    DAY_END,
    EVENING_START,
    MORNING_LATEST_START,
    Plan,
    is_daytime_only,
    is_evening_only,
    is_morning_only,
    is_night_spot,
    is_open,
)


def violations(plan: Plan) -> list[str]:
    out: list[str] = []
    did = plan.dest["id"]
    seen: set[str] = set()
    for day in plan.days:
        tag = f"{did} Day{day.number}({day.kind})"
        timed = [b for b in day.blocks if b.end > b.start and b.kind != "travel"]
        for a, b in zip(timed, timed[1:]):
            if a.end > b.start:
                out.append(f"{tag} 重なり: {a.title} {planner.fmt_time(a.end)} > {b.title} {planner.fmt_time(b.start)}")
        for b in day.blocks:
            if b.kind == "spot":
                s = b.spot
                if s["name"] in seen:
                    out.append(f"{tag} 同じスポット 2 回: {s['name']}")
                seen.add(s["name"])
                if not is_open(s, day.date):
                    out.append(f"{tag} 休み・季節外に訪問: {s['name']}")
                if is_morning_only(s) and b.start > MORNING_LATEST_START:
                    out.append(f"{tag} 朝のスポットが {planner.fmt_time(b.start)}: {s['name']}")
                if is_evening_only(s) and b.start < EVENING_START:
                    out.append(f"{tag} 夕方のスポットが {planner.fmt_time(b.start)}: {s['name']}")
                if is_daytime_only(s) and b.end > DAY_END:
                    out.append(f"{tag} 日中のスポットが {planner.fmt_time(b.end)} まで: {s['name']}")
                if is_night_spot(s) and b.start < 19 * 60:
                    out.append(f"{tag} 夜のスポットが {planner.fmt_time(b.start)}: {s['name']}")
            if b.kind == "meal" and b.start > 22 * 60 + 30:
                out.append(f"{tag} 深夜の食事: {b.title} {planner.fmt_time(b.start)}")
        if day.kind not in ("transit", "home"):
            covers_noon = any(b.start <= 12 * 60 + 30 <= b.end for b in day.blocks)
            if covers_noon and not any(b.title.startswith("昼食") for b in day.blocks):
                out.append(f"{tag} 昼食がない")
        if day.lodging:
            if not any(b.title.startswith("夕食") for b in day.blocks):
                out.append(f"{tag} 泊まる日なのに夕食がない")
            checkin = next(b for b in day.blocks if b.kind == "lodging")
            arrivals = [b.end for b in day.blocks if b.kind == "travel"]
            if arrivals and checkin.start < max(arrivals):
                out.append(f"{tag} 到着前にチェックイン: {planner.fmt_time(checkin.start)} < {planner.fmt_time(max(arrivals))}")
        for s in day.rain_plan:
            if s["name"] in {b.spot["name"] for d in plan.days for b in d.blocks if b.spot}:
                out.append(f"{tag} 雨の代案が訪問済み: {s['name']}")
            if is_night_spot(s) or not is_open(s, day.date):
                out.append(f"{tag} 雨の代案が不適切: {s['name']}")
        if day.mission and not day.has_activity:
            out.append(f"{tag} 移動だけの日にミッション")
    if plan.total != sum(plan.costs.values()):
        out.append(f"{did} 合計が内訳と合わない")
    lodging_nights = sum(1 for d in plan.days if d.lodging)
    transit = sum(1 for o in (plan.access_out, plan.access_back) if o.get("overnight"))
    if lodging_nights + transit != plan.cond.nights:
        out.append(f"{did} 泊数が合わない: 宿 {lodging_nights} + 夜行 {transit} != {plan.cond.nights}")
    if plan.over_budget and any("収まる" in r for r in plan.reasons):
        out.append(f"{did} 予算オーバーなのに「収まる」と説明")
    return out
