"""旅程を決め込み度に応じた Markdown にする（画面表示とダウンロードの両方で使う）。"""

from __future__ import annotations

from datetime import date

from .constants import (
    ACCESS_MODES,
    DETAIL_LEVELS,
    GENRES,
    HUBS,
    LODGING_TIERS,
    NICHE_LABELS,
    PACES,
    RELATIONS,
)
from .engine import SCORE_LABELS
from .planner import Day, Plan, fmt_time, lodging_label, maps_url, reverse_route, spot_query

WEEKDAYS = "月火水木金土日"

COST_LABELS = {
    "transport": "交通費（往復）",
    "lodging": "宿泊費",
    "food": "食費",
    "local": "現地の移動",
    "activities": "入場料・体験料",
}


def yen(n: int | float) -> str:
    return f"{int(round(n)):,}円"


def fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def party_text(plan: Plan) -> str:
    c = plan.cond
    kids = f"・子ども{c.kids}人" if c.kids else ""
    return f"{RELATIONS[c.relation]}（大人{c.adults}人{kids}）"


def span_text(plan: Plan) -> str:
    c = plan.cond
    if c.nights == 0:
        return f"{fmt_date(c.start_date)} 日帰り"
    return f"{fmt_date(c.start_date)}〜{fmt_date(c.end_date)}（{c.nights}泊{c.days}日）"


def dest_names(plan: Plan) -> str:
    return " → ".join(s.dest["name"] for s in plan.stops)


# ════════════════════════════════════════════════════════════════════
# セクションごとの Markdown
# ════════════════════════════════════════════════════════════════════
def overview_md(plan: Plan, with_header: bool = True) -> str:
    d = plan.dest
    lines = []
    if with_header:
        pref = "・".join(dict.fromkeys(s.dest["pref"] for s in plan.stops))
        lines.append(f"### {dest_names(plan)}")
        lines.append(f"{pref}　｜　{NICHE_LABELS[d['niche']]}　｜　{span_text(plan)}　｜　{party_text(plan)}")
        lines.append("")
    lines.append(f"**{d['tagline']}**")
    lines.append("")
    lines.append(d["description"])
    if len(plan.stops) > 1:
        d2 = plan.stops[1].dest
        lines.append("")
        lines.append(f"後半は **{d2['name']}** へ。{d2['tagline']}")
    return "\n".join(lines)


def reasons_md(plan: Plan) -> str:
    return "\n".join(f"- {r}" for r in plan.reasons)


def budget_summary_md(plan: Plan) -> str:
    c = plan.cond
    head = f"**概算 {yen(plan.total)}**（1人あたり 約{yen(plan.per_person)}）／ 予算 {yen(c.budget_total)} → "
    if plan.over_budget:
        body = head + f"**予算を約 {yen(plan.total - c.budget_total)} オーバー**"
    else:
        usage = plan.total / c.budget_total * 100 if c.budget_total else 0
        body = head + f"予算の {usage:.0f}%　残り {yen(c.budget_total - plan.total)} はおみやげ・予備費に"
    notes = [n for n in (plan.fallback_note, plan.tier_note) if n]
    return "\n\n".join([body] + [f"※ {n}" for n in notes])


def access_md(plan: Plan) -> str:
    c = plan.cond
    out, back = plan.access_out, plan.access_back
    lines = [
        f"- **行き**（{HUBS[c.hub]}発）：{out['route']}　"
        f"{ACCESS_MODES[out['mode']]}・片道 約{out['hours']:.1f}時間・大人1人 約{yen(out['cost'])}"
        + ("・夜行" if out.get("overnight") else ""),
    ]
    if plan.transfer:
        t = plan.transfer
        lines.append(f"- **周遊**：{t['route']}　約{t['hours']:.1f}時間・大人1人 約{yen(t['cost'])}")
    lines.append(
        f"- **帰り**：{reverse_route(back['route'])}　"
        f"{ACCESS_MODES[back['mode']]}・片道 約{back['hours']:.1f}時間・大人1人 約{yen(back['cost'])}"
        + ("・夜行" if back.get("overnight") else ""))
    for st in plan.stops:
        lt = st.dest["local_transport"]
        car = "（レンタカー前提）" if lt["car"] else ""
        lines.append(f"- **現地の移動**（{st.dest['name']}）：{lt['note']}{car}")
    return "\n".join(lines)


def lodging_md(plan: Plan) -> str:
    if plan.cond.nights == 0:
        return "日帰りなので宿は不要です。"
    lines = []
    for st in plan.stops:
        if not st.nights:
            continue
        lo = st.dest["lodging"][plan.tier]
        lines.append(f"- **{st.dest['name']}**：{lodging_label(lo)}"
                     f"× {st.nights}泊　目安 1人1泊 約{yen(lo['price'])}〜（2名1室・通常期）")
    lines.append(f"- 宿の段階：{LODGING_TIERS[plan.tier]}")
    if plan.tier_note:
        lines.append(f"- {plan.tier_note}")
    return "\n".join(lines)


def highlights_md(plan: Plan) -> str:
    lines = []
    for s in plan.highlights:
        fee = "無料" if s["cost"] == 0 else f"約{yen(s['cost'])}"
        lines.append(f"- **{s['name']}**（{s['area']}・{NICHE_LABELS[s['niche']]}・{fee}）— {s['note']}"
                     f"　[地図]({maps_url(spot_query(s, plan.stop_of(s)))})")
    return "\n".join(lines)


def foods_md(plan: Plan) -> str:
    return "\n".join(f"- **{f['name']}**（1人 約{yen(f['price'])}）— {f.get('note', '')}" for f in plan.must_eat)


def budget_table_md(plan: Plan) -> str:
    people = max(1, plan.cond.people)
    lines = ["| 項目 | グループ合計 | 1人あたり |", "|---|---:|---:|"]
    for key, label in COST_LABELS.items():
        v = plan.costs.get(key, 0)
        lines.append(f"| {label} | {yen(v)} | {yen(v / people)} |")
    lines.append(f"| **合計** | **{yen(plan.total)}** | **{yen(plan.total / people)}** |")
    return "\n".join(lines)


def tips_md(plan: Plan) -> str:
    tips = [t for st in plan.stops for t in st.dest["tips"]]
    extra = []
    for st in plan.stops:
        if st.dest["region"] == "overseas" and st.dest.get("notes_overseas"):
            extra.append(f"**渡航メモ（{st.dest['name']}）**：{st.dest['notes_overseas']}")
    return "\n".join([f"- {t}" for t in tips] + ([""] + extra if extra else []))


def _part_of_day(minutes: int) -> str:
    if minutes < 12 * 60:
        return "午前"
    if minutes < 17 * 60:
        return "午後"
    return "夜"


def day_header(day: Day) -> str:
    return f"Day {day.number}　{fmt_date(day.date)}　{day.theme}"


def day_outline_md(day: Day) -> str:
    """決め込み度 3：時刻なしで、午前・午後・夜に何をするか。"""
    groups: dict[str, list[str]] = {"午前": [], "午後": [], "夜": []}
    meals = []
    for b in day.blocks:
        if b.kind == "spot":
            groups[_part_of_day(b.start)].append(b.title)
        elif b.kind in ("meal", "snack") and not b.title.startswith("朝食"):
            meals.append(b.title)
        elif b.kind == "travel":
            groups[_part_of_day(b.start)].append(b.title)
    lines = []
    for part, items in groups.items():
        if items:
            lines.append(f"- **{part}**：{' → '.join(items)}")
    if meals:
        lines.append(f"- **食事**：{' ／ '.join(meals)}")
    if day.lodging:
        lines.append(f"- **宿**：{day.lodging}")
    return "\n".join(lines) if lines else "- 移動日"


def day_schedule_md(day: Day, with_costs: bool) -> str:
    """決め込み度 4〜5：時刻入りの表。"""
    head = "| 時刻 | 予定 | メモ |" + (" 費用 |" if with_costs else "")
    sep = "|---|---|---|" + ("---:|" if with_costs else "")
    lines = [head, sep]
    for b in day.blocks:
        if b.kind == "move" and not with_costs:
            continue
        t = fmt_time(b.start) if b.start == b.end else f"{fmt_time(b.start)}〜{fmt_time(b.end)}"
        title = b.title
        if b.maps_query:
            title = f"{title} [地図]({maps_url(b.maps_query)})"
        note = b.detail.replace("|", "／")
        row = f"| {t} | {title} | {note} |"
        if with_costs:
            row += f" {yen(b.cost) if b.cost else '—'} |"
        lines.append(row)
    return "\n".join(lines)


def rain_md(day: Day) -> str:
    if not day.rain_plan:
        return ""
    names = "、".join(s["name"] for s in day.rain_plan)
    return f"☔ 雨ならこちら：{names}"


def days_md(plan: Plan, level: int, heading: str = "###") -> str:
    out = []
    for day in plan.days:
        out.append(f"{heading} {day_header(day)}")
        if level >= 4:
            out.append(day_schedule_md(day, with_costs=level >= 5))
            if day.lodging:
                out.append(f"\n宿：{day.lodging}")
            rain = rain_md(day)
            if rain:
                out.append(f"\n{rain}")
        else:
            out.append(day_outline_md(day))
        if level >= 5 and day.mission:
            out.append(f"\n🎯 今日のミッション：{day.mission}")
        out.append("")
    return "\n".join(out)


def checklist_md(items: list[str]) -> str:
    return "\n".join(f"- [ ] {i}" for i in items)


def score_md(plan: Plan) -> str:
    parts = plan.candidate.parts
    lines = ["| 観点 | 一致度 |", "|---|---:|"]
    for k, label in SCORE_LABELS.items():
        lines.append(f"| {label} | {parts[k] * 100:.0f}% |")
    lines.append(f"| **総合** | **{plan.candidate.score * 100:.0f}%** |")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# まとめ
# ════════════════════════════════════════════════════════════════════
def sections(plan: Plan, level: int, day_heading: str = "###", with_header: bool = True) -> list[tuple[str, str]]:
    """(見出し, 本文) のリスト。見出しが空なら本文だけを置く。"""
    out: list[tuple[str, str]] = [("", overview_md(plan, with_header)), ("この行き先になった理由", reasons_md(plan)),
                                  ("予算", budget_summary_md(plan))]
    if level == 1:
        out.append(("", "_交通・宿・回り方は自由に。決め込み度を上げると、ここから先も決めます。_"))
        return out
    out[-1] = ("予算", budget_summary_md(plan) + "\n\n" + budget_table_md(plan))
    out.append(("アクセス", access_md(plan)))
    out.append(("宿", lodging_md(plan)))
    if level in (2, 3):
        out.append(("見どころ" if level == 3 else "見どころ候補", highlights_md(plan)))
    out.append(("食べたいもの", foods_md(plan)))
    if level >= 3:
        out.append(("旅程", days_md(plan, level, day_heading)))
    out.append(("ひとことメモ", tips_md(plan)))
    if level >= 5:
        out.append(("予約するものリスト", checklist_md(plan.bookings)))
        out.append(("持ち物リスト", checklist_md(plan.packing)))
    return out


def data_basis_md(plan: Plan) -> str:
    from .data import DATA_BASIS_LABELS
    lines = []
    for st in plan.stops:
        basis = st.dest.get("data_basis")
        if basis in DATA_BASIS_LABELS:
            lines.append(f"- {st.dest['name']}：{DATA_BASIS_LABELS[basis]}")
    return "\n".join(lines)


def conditions_md(plan: Plan) -> str:
    c = plan.cond
    genres = "・".join(GENRES[g] for g in c.genres) or "おまかせ"
    return "\n".join([
        f"- 出発：{HUBS[c.hub]}",
        f"- 日程：{span_text(plan)}",
        f"- 人数・関係性：{party_text(plan)}",
        f"- 予算：合計 {yen(c.budget_total)}",
        f"- ジャンル：{genres}",
        f"- 王道〜ニッチ：{NICHE_LABELS[c.niche]}",
        f"- ペース：{PACES[c.pace]}",
    ])


def to_markdown(plan: Plan, level: int) -> str:
    lines = [f"# {plan.title}", "", f"決め込み度：{level}（{DETAIL_LEVELS[level]}）　旅コード：{plan.trip_code}", ""]
    for heading, body in sections(plan, level):
        if heading:
            lines += [f"## {heading}", ""]
        lines += [body, ""]
    lines += ["## 条件", "", conditions_md(plan), ""]
    basis = data_basis_md(plan)
    if basis:
        lines += ["## データの確認状況", "", basis, ""]
    lines += ["---", "",
              "※ 金額・所要時間は 2026 年 9 月時点の公開情報をもとにした目安です。営業日・料金・ダイヤは変わることがあるため、"
              "予約前に必ず公式情報で確認してください。"]
    return "\n".join(lines)


CLAUDE_REQUESTS = {
    1: ["行き先がこの条件（予算・日程・人数・関係性・好み）に本当に合っているかを、根拠つきで評価する",
        "この行き先の概算費用（交通・宿・食事）を最新の情報で見積もり直す",
        "時期的な注意点（休業・混雑・天候・イベント）を挙げる",
        "旅程や店・宿は決めない。自分で考えるための材料だけを渡す"],
    2: ["交通手段と所要時間・運賃を最新のダイヤ・運賃で確認し、より良い行き方があれば示す",
        "宿のエリアとタイプの候補を、価格帯つきで 2〜3 通り挙げる（具体的な宿名までは決めなくてよい）",
        "見どころ候補の営業状況・料金・定休日を確認し、成り立たないものを指摘する",
        "日ごとの時間割は作らない。大枠の確認にとどめる"],
    3: ["日ごとの流れ（午前・午後・夜に回る場所）が移動時間・営業時間の面で成り立つかを確認して直す",
        "各日の食事の候補を、価格帯つきで挙げる",
        "予算内に収まっているかを再計算し、超える場合は削る順番を提案する",
        "分刻みの時間割までは作らない"],
    4: ["各スポット・店・交通の営業日、営業時間、料金、運行ダイヤを確認し、成り立たない箇所を指摘して直す",
        "移動時間に無理がある箇所を組み替える（旅のペースは維持）",
        "雨の日の代案が実際に使えるかを確認する",
        "予算内に収まっているかを再計算し、超える場合は削る順番を提案する"],
    5: ["各スポット・店・交通の営業日、営業時間、料金、運行ダイヤを確認し、成り立たない箇所を指摘して直す",
        "食事の具体的な店の候補と、宿の具体的な候補を価格帯つきで 2〜3 件ずつ挙げる",
        "予約リストの各項目について、予約開始時期と方法を確認する",
        "予算内に収まっているかを再計算し、超える場合は削る順番を提案する"],
}


def claude_prompt(plan: Plan, level: int) -> str:
    """Claude.ai に貼って仕上げてもらうためのプロンプト。決め込み度と同じ細かさで頼む。"""
    body = to_markdown(plan, level)
    requests = [f"{i}. {r}" for i, r in enumerate(CLAUDE_REQUESTS[level], 1)]
    return "\n".join([
        "あなたは国内外の旅行計画に詳しいトラベルプランナーです。",
        f"以下は、条件からランダムに自動生成した旅行プランの叩き台です（決め込み度：{DETAIL_LEVELS[level]}）。",
        "",
        "## お願いしたいこと",
        *requests,
        "",
        "## 守ってほしいこと",
        "- 確認できない情報を断定しない。未確認のものは「要確認」と明記する",
        "- 情報源（公式サイトなど）と、その情報がいつ時点のものかを添える",
        "- 叩き台の良くない点ははっきり指摘する",
        "",
        "---",
        "",
        body,
    ])
