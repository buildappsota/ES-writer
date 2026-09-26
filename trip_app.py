"""ランダム旅行メーカー（Streamlit）。

    streamlit run trip_app.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import streamlit as st

from trip_maker import engine, planner, render
from trip_maker.constants import (
    DETAIL_DESCRIPTIONS,
    DETAIL_LEVELS,
    GENRES,
    HUBS,
    LODGING_PREFS,
    NICHE_LABELS,
    PACES,
    RELATIONS,
    SCOPES,
    TRANSPORT_PREFS,
)
from trip_maker.data import load_destinations

st.set_page_config(page_title="ランダム旅行メーカー", page_icon="🎲", layout="wide")

SURPRISE_LABELS = {
    1: "条件ぴったり",
    2: "ほぼ条件どおり",
    3: "ほどよく意外",
    4: "かなり意外",
    5: "完全ランダム",
}
MULTI_STOP = {"auto": "おまかせ（長い旅なら 2 か所めぐり）", "off": "1 か所でじっくり", "on": "できれば 2 か所めぐる"}
GENRE_ICONS = {"onsen": "♨️", "gourmet": "🍜", "nature": "🏞️", "history": "⛩️", "art": "🎨",
               "activity": "🚴", "town": "🏘️", "beach": "🏖️", "remote": "🏝️", "drink": "🍶"}
HISTORY_MAX = 10


@st.cache_resource
def destinations() -> list[dict]:
    return load_destinations(strict=False)


def next_saturday(today: date) -> date:
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def new_seed() -> int:
    return random.SystemRandom().randrange(100000, 1000000)


# ════════════════════════════════════════════════════════════════════
# CSS
# ════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 2rem;}
.section-label {
    font-size: 0.78rem; font-weight: 600; letter-spacing: 0.06em;
    color: #868e96; margin: 18px 0 4px;
}
.trip-hero {
    background: linear-gradient(135deg, #0b7285 0%, #1864ab 100%);
    color: #fff; border-radius: 12px; padding: 18px 22px; margin-bottom: 12px;
}
.trip-hero h2 {color: #fff; margin: 0 0 6px; font-size: 1.35rem; line-height: 1.4;}
.trip-hero .meta {opacity: 0.9; font-size: 0.9rem;}
.chip {
    display: inline-block; background: rgba(255,255,255,0.18); border-radius: 20px;
    padding: 2px 10px; margin: 6px 6px 0 0; font-size: 0.82rem;
}
.notice {
    background: #fff4e6; border-left: 3px solid #e8590c; padding: 8px 12px;
    border-radius: 0 6px 6px 0; font-size: 0.9rem; margin-bottom: 10px;
}
.stButton > button {border-radius: 8px; font-weight: 500;}
/* 選択肢（pills）は横スクロールにせず折り返す */
.stButtonGroup > div {flex-wrap: wrap !important; overflow-x: visible !important; row-gap: 6px;}
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════
# 生成
# ════════════════════════════════════════════════════════════════════
def generate(cond: engine.Conditions, dest_seed: int, plan_seed: int, forced_id: str | None = None,
             avoid_id: str | None = None) -> None:
    """旅を作って session_state.plan に入れる。

    forced_id：その行き先で作る（旅コードに行き先 id が残る）。
    avoid_id：その行き先以外から抽選する（「別の行き先で引き直す」用。結果は行き先指定の旅として扱う）。
    """
    st.session_state.error = None
    dests = destinations()
    result = engine.search(dests, cond)
    info = {"scope_count": result.scope_count, "candidates": len(result.candidates),
            "genre_relaxed": result.genre_relaxed}
    if forced_id:
        cand = next((c for c in result.candidates if c.dest["id"] == forced_id), None)
        if cand is None:
            st.session_state.error = "今の条件ではその行き先は選べません（予算・日数・季節などを確認してください）。"
            return
        others = [c for c in result.candidates if c.dest["id"] != forced_id]
        alternatives = engine.pick(others, cond.surprise, random.Random(f"alt-{dest_seed}"), k=3)
        plan = planner.make_plan(cand, cond, dests, dest_seed, plan_seed, alternatives, forced=True,
                                 genre_relaxed=result.genre_relaxed)
    else:
        pool = [c for c in result.candidates if c.dest["id"] != avoid_id]
        if not pool:
            st.session_state.plan = None
            st.session_state.no_result = result
            if avoid_id and result.candidates:
                st.session_state.error = "条件に合う行き先がほかにありません。"
            return
        picked = engine.pick(pool, cond.surprise, random.Random(f"dest-{dest_seed}"), k=4)
        plan = planner.make_plan_from_candidates(picked, cond, dests, dest_seed, plan_seed,
                                                 forced=avoid_id is not None, genre_relaxed=result.genre_relaxed)
    plan.search_info = info
    st.session_state.plan = plan
    st.session_state.no_result = None
    st.session_state.plan_fp = cond.fingerprint()
    history = [p for p in st.session_state.history if p.dest["id"] != plan.dest["id"]]
    st.session_state.history = ([plan] + history)[:HISTORY_MAX]


for key, default in {"plan": None, "plan_fp": None, "no_result": None, "error": None, "history": []}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ════════════════════════════════════════════════════════════════════
# ヘッダー
# ════════════════════════════════════════════════════════════════════
st.markdown("## 🎲 ランダム旅行メーカー")
st.caption("予算・日程・人数・関係性・好みを入れると、行き先と旅程をランダムに提案します。"
           "どこまで決めるか（行き先だけ〜全部おまかせ）は「決め込み度」で選べます。")

col_in, col_out = st.columns([1, 1.7], gap="large")

# ════════════════════════════════════════════════════════════════════
# 入力
# ════════════════════════════════════════════════════════════════════
with col_in:
    st.markdown('<p class="section-label">いつ・どこから・だれと</p>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        hub = st.selectbox("出発エリア", list(HUBS), index=list(HUBS).index("tokyo"), format_func=HUBS.get)
    with c2:
        today = date.today()
        start_date = st.date_input("出発日", value=next_saturday(today), min_value=today,
                                   max_value=today + timedelta(days=730), format="YYYY/MM/DD")
    nights = st.select_slider("日数", options=list(range(0, 8)), value=1,
                              format_func=lambda n: "日帰り" if n == 0 else f"{n}泊{n + 1}日")

    relation = st.radio("関係性", list(RELATIONS), index=list(RELATIONS).index("friends"),
                        format_func=RELATIONS.get, horizontal=True)
    if relation == "solo":
        adults, kids = 1, 0
        st.caption("ひとり旅：大人 1 人で計算します。")
    else:
        c1, c2 = st.columns(2)
        with c1:
            adults = st.number_input("大人", min_value=1, max_value=20, value=2, step=1)
        with c2:
            kids = st.number_input("子ども（小学生以下）", min_value=0, max_value=10, value=0, step=1)
    if relation == "family_kids" and kids == 0:
        st.caption("子どもの人数を入れると、運賃・宿代の子ども料金を反映します。")

    st.markdown('<p class="section-label">予算</p>', unsafe_allow_html=True)
    c1, c2 = st.columns([1.3, 1])
    with c1:
        budget_value = st.number_input("金額（円・交通費込み）", min_value=5000, max_value=5_000_000,
                                       value=50000, step=5000)
    with c2:
        budget_mode = st.radio("金額の単位", ["1人あたり", "全員の合計"], horizontal=False)
    people = adults + kids
    budget_total = int(budget_value * people) if budget_mode == "1人あたり" else int(budget_value)
    st.caption(f"全員の合計：{render.yen(budget_total)}（{people}人）")

    st.markdown('<p class="section-label">好み</p>', unsafe_allow_html=True)
    genres = st.pills("ジャンル（複数可・未選択ならおまかせ）", list(GENRES),
                      format_func=lambda g: f"{GENRE_ICONS[g]} {GENRES[g]}", selection_mode="multi") or []
    niche = st.select_slider("王道 ↔ ニッチ", options=list(NICHE_LABELS), value=3, format_func=NICHE_LABELS.get)
    surprise = st.select_slider("サプライズ度（条件からどれだけ外れてもいいか）", options=list(SURPRISE_LABELS),
                                value=2, format_func=SURPRISE_LABELS.get)

    st.markdown('<p class="section-label">決め込み度（プランをどこまで決めるか）</p>', unsafe_allow_html=True)
    detail = st.select_slider("決め込み度", options=list(DETAIL_LEVELS), value=3,
                              format_func=lambda n: f"{n}. {DETAIL_LEVELS[n]}", label_visibility="collapsed")
    st.caption(f"{DETAIL_LEVELS[detail]}：{DETAIL_DESCRIPTIONS[detail]}（あとから動かしても旅は変わりません）")

    with st.expander("こだわり条件"):
        scope = st.radio("行き先の範囲", list(SCOPES), format_func=SCOPES.get, horizontal=True)
        transport_pref = st.selectbox("移動手段", list(TRANSPORT_PREFS), format_func=TRANSPORT_PREFS.get)
        lodging_pref = st.selectbox("宿", list(LODGING_PREFS), format_func=LODGING_PREFS.get)
        pace = st.radio("旅のペース", list(PACES), index=1, format_func=PACES.get, horizontal=True)
        multi_stop = st.radio("周遊", list(MULTI_STOP), format_func=MULTI_STOP.get)
        all_dests = destinations()
        name_of = {d["id"]: f"{d['name']}（{d['pref']}）" for d in all_dests}
        exclude_ids = st.multiselect("行ったことがある・除外したい行き先", list(name_of), format_func=name_of.get)
        trip_code = st.text_input("旅コード（同じ条件で同じ旅を再現）", placeholder="例：123456-654321").strip()

    cond = engine.Conditions(
        hub=hub, start_date=start_date, nights=nights, adults=int(adults), kids=int(kids), relation=relation,
        budget_total=budget_total, genres=list(genres), niche=niche, detail=detail, surprise=surprise,
        scope=scope, pace=pace, transport_pref=transport_pref, lodging_pref=lodging_pref,
        multi_stop=multi_stop, exclude_ids=list(exclude_ids),
    )

    if st.button("🎲 旅をつくる", type="primary", use_container_width=True):
        if trip_code:
            parsed = planner.parse_trip_code(trip_code)
            if parsed is None:
                st.session_state.error = "旅コードは「数字-数字」または「数字-数字-行き先」の形で入力してください。"
            else:
                generate(cond, parsed[0], parsed[1], forced_id=parsed[2])
        else:
            generate(cond, new_seed(), new_seed())

    st.caption(f"収録：{len(destinations())} か所（国内 {sum(d['region'] != 'overseas' for d in destinations())}・"
               f"海外 {sum(d['region'] == 'overseas' for d in destinations())}）")


# ════════════════════════════════════════════════════════════════════
# 結果
# ════════════════════════════════════════════════════════════════════
def show_no_result(result: engine.Search, cond: engine.Conditions) -> None:
    st.warning("条件に合う行き先が見つかりませんでした。")
    reasons: dict[str, int] = {}
    for e in result.excluded:
        for r in e.reasons_excluded:
            key = r.split("（")[0]
            reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        st.markdown("**外れた理由（件数）**")
        st.markdown("\n".join(f"- {k}：{v} 件" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))
    hint = engine.budget_hint(result.excluded, cond)
    if hint:
        gap, d = hint
        if budget_mode == "1人あたり" and cond.people > 1:
            per = -(-gap // cond.people)
            per = -(-per // 1000) * 1000
            st.info(f"予算を 1 人あたり約 {render.yen(per)}（全員で約 {render.yen(gap)}）増やすと"
                    f"「{d['name']}」が候補に入ります。")
        else:
            st.info(f"予算をあと約 {render.yen(gap)} 増やすと「{d['name']}」が候補に入ります。")
    if cond.nights == 0:
        st.info("日帰りは片道 3.5 時間以内の行き先に限っています。1 泊にすると候補が増えます。")


def show_plan(plan: planner.Plan, level: int) -> None:
    c = plan.cond
    chips = [NICHE_LABELS[plan.dest["niche"]], render.span_text(plan), render.party_text(plan),
             f"概算 {render.yen(plan.total)}"]
    st.markdown(
        f'<div class="trip-hero"><h2>{plan.title}</h2>'
        f'<div class="meta">{render.dest_names(plan)}（{"・".join(dict.fromkeys(s.dest["pref"] for s in plan.stops))}）</div>'
        + "".join(f'<span class="chip">{x}</span>' for x in chips) + "</div>",
        unsafe_allow_html=True,
    )
    usage = min(1.0, plan.total / c.budget_total) if c.budget_total else 0
    st.progress(usage, text=f"予算の使い方：{render.yen(plan.total)} / {render.yen(c.budget_total)}"
                + ("（予算オーバー）" if plan.over_budget else ""))

    b1, b2 = st.columns(2)
    with b1:
        if st.button("🎲 別の行き先で引き直す", use_container_width=True):
            generate(cond, new_seed(), new_seed(), avoid_id=plan.dest["id"])
            st.rerun()
    with b2:
        if st.button("🔁 行き先はそのまま、プランだけ引き直す", use_container_width=True):
            generate(cond, plan.dest_seed, new_seed(), forced_id=plan.dest["id"])
            st.rerun()

    for heading, body in render.sections(plan, level, day_heading="#####", with_header=False):
        if heading:
            st.markdown(f"#### {heading}")
        st.markdown(body)

    basis = render.data_basis_md(plan)
    if basis:
        st.caption("データの確認状況（金額・所要時間はすべて目安。予約前に公式情報で確認してください）\n\n" + basis)

    with st.expander(f"他の候補（{len(plan.alternatives)} 件）"):
        if not plan.alternatives:
            st.caption("条件に合う行き先がほかにありません。")
        for alt in plan.alternatives:
            a1, a2 = st.columns([3, 1])
            with a1:
                d = alt.dest
                st.markdown(f"**{d['name']}**（{d['pref']}・{NICHE_LABELS[d['niche']]}）— {d['tagline']}  \n"
                            f"概算 {render.yen(alt.est.total)}・一致度 {alt.score * 100:.0f}%")
            with a2:
                if st.button("この行き先で作る", key=f"alt_{d['id']}", use_container_width=True):
                    generate(cond, plan.dest_seed, new_seed(), forced_id=d["id"])
                    st.rerun()

    with st.expander("選ばれた理由とスコア"):
        info = plan.search_info
        if info:
            st.caption(f"範囲内 {info['scope_count']} か所のうち、条件を満たしたのは {info['candidates']} か所。"
                       "そこからスコアとサプライズ度に応じた重み付き抽選で選んでいます。")
        st.markdown(render.score_md(plan))

    with st.expander("書き出す・Claude で仕上げる"):
        md = render.to_markdown(plan, level)
        st.download_button("Markdown で保存", md, file_name=f"trip_{plan.trip_code}.md",
                           mime="text/markdown", use_container_width=True)
        st.caption(f"旅コード：{plan.trip_code}（同じ条件でこのコードを入れると同じ旅を再現できます）")
        st.markdown("下のプロンプトをコピーして [Claude.ai](https://claude.ai/) に貼ると、"
                    "営業時間・料金の確認や具体的な店・宿の候補出しを頼めます。")
        st.code(render.claude_prompt(plan, level), language=None)


with col_out:
    plan = st.session_state.plan
    if st.session_state.error:
        st.error(st.session_state.error)
    if plan is None:
        result = st.session_state.no_result
        if result is not None and not result.candidates:
            show_no_result(result, cond)
        else:
            st.info("左で条件を選んで「🎲 旅をつくる」を押してください。")
            st.markdown(
                "**決め込み度のちがい**\n\n"
                + "\n".join(f"{n}. **{DETAIL_LEVELS[n]}** — {DETAIL_DESCRIPTIONS[n]}" for n in DETAIL_LEVELS)
            )
    else:
        if st.session_state.plan_fp != cond.fingerprint():
            st.markdown('<div class="notice">条件が変わっています。反映するには「🎲 旅をつくる」を押してください。'
                        '（決め込み度だけはそのまま反映されます）</div>', unsafe_allow_html=True)
        show_plan(plan, detail)

    history = st.session_state.history
    if len(history) > 1:
        with st.expander(f"これまでに引いた旅（{len(history)} 件）"):
            for i, past in enumerate(history):
                h1, h2 = st.columns([4, 1])
                with h1:
                    st.markdown(f"{past.title}　{render.yen(past.total)}")
                with h2:
                    if plan is not None and past is plan:
                        st.caption("表示中")
                    elif st.button("表示", key=f"hist_{i}", use_container_width=True):
                        st.session_state.plan = past
                        st.session_state.plan_fp = past.cond.fingerprint()
                        st.session_state.error = None
                        st.rerun()
