"""旅程が満たすべき性質のチェック（テストと調査スクリプトの両方で使う）。"""

from trip_maker import planner
from trip_maker.planner import Plan, is_night_spot, is_open
from trip_maker.rules import fits_time, link_mode


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
                if not fits_time(s, b.start, b.end):
                    out.append(f"{tag} 時間帯の外: {s['name']} {planner.fmt_time(b.start)}〜"
                               f"{planner.fmt_time(b.end)} when={s['when']}")
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
    if plan.over_budget and any("% に収まる" in r for r in plan.reasons):
        out.append(f"{did} 予算オーバーなのに「収まる」と説明")
    c = plan.cond
    for st in plan.stops[1:]:
        d = st.dest
        if c.scope != "both" and (c.scope == "domestic") != (d["region"] != "overseas"):
            out.append(f"{did} 周遊先が範囲外: {d['id']}")
        if min(o["hours"] for o in d["access"][c.hub]) <= planner.HUB_CITY_HOURS:
            out.append(f"{did} 周遊先が出発地: {d['id']}")
    if plan.transfer and c.transport_pref == "no_flight" and link_mode(plan.transfer) == "flight":
        out.append(f"{did} 飛行機なしなのに周遊の移動が飛行機")
    for day in plan.days:
        if day.mission in planner.EVENING_MISSIONS and not day.lodging:
            out.append(f"{did} Day{day.number} 夜のミッションなのに現地に泊まらない")
    return out
