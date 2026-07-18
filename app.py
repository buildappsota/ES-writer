import json
import re
from datetime import datetime
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="ESプロンプトビルダー", page_icon="✏️", layout="wide")

HISTORY_FILE = Path(__file__).parent / "es_history.json"

PASSIVE_PATTERNS = [
    "を知りたい", "を確かめたい", "を学びたい", "を感じたい",
    "に貢献できればと思います", "と思っています", "できればと思います",
    "したいと思います", "いければと思います",
]

QUESTION_TYPE_HINTS: list[tuple[list[str], str]] = [
    (["志望", "なぜ", "理由", "動機", "選んだ"], "志望動機"),
    (["挫折", "失敗", "壁", "困難", "乗り越え", "つらかった", "苦労"], "挫折経験"),
    (["弱み", "短所", "苦手", "長所と短所", "強みと弱み"], "強み・弱み"),
    (["強み", "長所", "得意", "自己PR", "あなたらしさ"], "自己PR"),
    (["学生時代", "ガクチカ", "力を入れた", "打ち込ん", "頑張った", "取り組ん"], "ガクチカ"),
]

# ── セッション初期化 ────────────────────────────────────────────────
def init_session():
    defaults = {
        "name": "",
        "university": "",
        "gakuchikas": [{"situation": "", "challenge": "", "action": "", "result": "", "learning": ""}],
        "strengths": [],
        "achievements": [{"before": "", "after": "", "period": "", "scale": ""}],
        "company": "",
        "industry": "",
        "question": "",
        "char_limit": 400,
        "reference_es_list": [""],
        "research_notes": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# ── プロフィール ────────────────────────────────────────────────────
def profile_to_dict() -> dict:
    return {
        "name": st.session_state.name,
        "university": st.session_state.university,
        "gakuchikas": st.session_state.gakuchikas,
        "strengths": st.session_state.strengths,
        "achievements": st.session_state.achievements,
    }

def load_profile(data: dict):
    st.session_state.name = data.get("name", "")
    st.session_state.university = data.get("university", "")
    st.session_state.gakuchikas = data.get("gakuchikas", [{"situation": "", "challenge": "", "action": "", "result": "", "learning": ""}])
    st.session_state.strengths = data.get("strengths", [])
    st.session_state.achievements = data.get("achievements", [{"before": "", "after": "", "period": "", "scale": ""}])

# ── 使用履歴 ────────────────────────────────────────────────────────
def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_history(entry: dict):
    history = load_history()
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def build_history_entry() -> dict:
    s = st.session_state
    used_gakuchikas = [
        g.get("situation", "")[:40] for g in s.gakuchikas
        if any(g.get(k) for k in ("situation", "challenge", "action", "result", "learning"))
    ]
    used_numbers = []
    for a in s.achievements:
        if a.get("before"):
            used_numbers.append(a["before"])
        if a.get("after"):
            used_numbers.append(a["after"])
    keywords = [kw.strip() for kw in re.split(r"[、,\s/／]+", s.research_notes) if kw.strip()][:10]
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "company": s.company,
        "question": s.question[:60],
        "char_limit": s.char_limit,
        "used_gakuchikas": used_gakuchikas,
        "used_numbers": used_numbers,
        "used_keywords": keywords,
    }

# ── ルールベース セルフチェック ────────────────────────────────────
def check_es_text(es_text: str, char_limit: int, achievements: list) -> list[dict]:
    results = []

    # 文字数充足率
    fill_rate = len(es_text) / char_limit * 100 if char_limit else 0
    threshold = int(char_limit * 0.9)
    if fill_rate < 90:
        results.append({
            "status": "warn",
            "label": "文字数",
            "message": f"{len(es_text)}/{char_limit}字（充足率 {fill_rate:.1f}%） — 9割（{threshold}字）未満です",
        })
    else:
        results.append({
            "status": "ok",
            "label": "文字数",
            "message": f"{len(es_text)}/{char_limit}字（充足率 {fill_rate:.1f}%）",
        })

    # 受け身表現の検出
    found = [p for p in PASSIVE_PATTERNS if p in es_text]
    if found:
        results.append({
            "status": "warn",
            "label": "受け身表現",
            "message": f"受け身・願望表現が含まれています：{'、'.join(found)}",
        })
    else:
        results.append({
            "status": "ok",
            "label": "受け身表現",
            "message": "受け身・願望表現は検出されませんでした",
        })

    # 実績数字との整合チェック
    number_issues = []
    for a in achievements:
        for field in ("before", "after"):
            val = a.get(field, "").strip()
            if not val:
                continue
            nums = re.findall(r"\d+", val)
            for n in nums:
                if n not in es_text:
                    number_issues.append(f"「{val}」の数値 {n}")
    if number_issues:
        results.append({
            "status": "warn",
            "label": "実績数字",
            "message": "本文中に見当たらない登録数値があります：" + "／".join(number_issues[:5]),
        })
    else:
        results.append({
            "status": "ok",
            "label": "実績数字",
            "message": "登録された実績数値はすべて本文中に確認できました（または実績未登録）",
        })

    return results

# ── 設問タイプ推定 ──────────────────────────────────────────────────
def guess_question_type(question: str) -> str | None:
    for keywords, label in QUESTION_TYPE_HINTS:
        if any(kw in question for kw in keywords):
            return label
    return None

# ── プロンプト生成 ──────────────────────────────────────────────────
def build_prompt() -> str:
    s = st.session_state
    lines = []

    lines.append("あなたは就活エントリーシートの添削・執筆の専門家です。以下の情報をもとに、エントリーシートの回答を作成してください。")
    lines.append("")

    # ── プロフィール ──
    lines.append("## 【応募者プロフィール】")
    lines.append(f"- 氏名：{s.name}")
    lines.append(f"- 所属：{s.university}")
    if s.strengths:
        lines.append(f"- 自己PRの軸となる強み：{' / '.join(s.strengths)}")

    valid_achievements = [a for a in s.achievements if a.get("before") or a.get("after")]
    if valid_achievements:
        lines.append("")
        lines.append("### 実績（数字）")
        for i, a in enumerate(valid_achievements, 1):
            parts = []
            if a.get("before") and a.get("after"):
                parts.append(f"{a['before']} → {a['after']}")
            if a.get("period"):
                parts.append(f"期間：{a['period']}")
            if a.get("scale"):
                parts.append(f"母数：{a['scale']}")
            lines.append(f"  実績{i}：{' ／ '.join(parts)}")

    valid_gakuchikas = [g for g in s.gakuchikas if any(g.get(k) for k in ("situation", "challenge", "action", "result", "learning"))]
    if valid_gakuchikas:
        lines.append("")
        lines.append("### 学生時代に力を入れたこと（ガクチカ）エピソード")
        for i, g in enumerate(valid_gakuchikas, 1):
            lines.append(f"  【エピソード{i}】")
            for key, label in [("situation", "状況"), ("challenge", "課題"), ("action", "行動"), ("result", "結果"), ("learning", "学び")]:
                if g.get(key):
                    lines.append(f"    {label}：{g[key]}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 応募情報 ──
    lines.append("## 【応募情報】")
    lines.append(f"- 企業名：{s.company}")
    lines.append(f"- 業界・職種：{s.industry}")
    lines.append(f"- ES設問：{s.question}")
    lines.append(f"- 指定文字数：{s.char_limit}字以内")

    if s.research_notes.strip():
        lines.append("")
        lines.append("### 企業研究メモ・この企業が使うキーワード")
        lines.append(s.research_notes.strip())

    valid_refs = [r for r in s.reference_es_list if r.strip()]
    if valid_refs:
        lines.append("")
        lines.append("### 参考：内定者ESの例文")
        lines.append("（※ 構成・熱量・文体の参考としてのみ使用すること。フレーズの丸写しは厳禁です。）")
        for i, ref in enumerate(valid_refs, 1):
            lines.append(f"\n【参考ES {i}】\n{ref.strip()}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ── フレームワーク定義（6種類） ──
    lines.append("## 【執筆フレームワーク定義】")
    lines.append("")
    lines.append("以下に6種類のフレームワークを定義します。どのタイプにも対応できるよう、すべて参照してください。")
    lines.append("")

    lines.append("### タイプ1：自己PR")
    lines.append("1. **強みの提示**：最も伝えたい強みを一言で明示する")
    lines.append("2. **裏付けエピソード**：その強みが発揮された具体的な経験（行動・工夫・結果を含む）")
    lines.append("3. **仕事での活かし方**：入社後にその強みをどう活かすかを具体的に述べる")
    lines.append("")

    lines.append("### タイプ2：ガクチカ（学生時代に力を入れたこと）")
    lines.append("1. **結論**：何に最も力を入れたかを一文で")
    lines.append("2. **課題・目標**：取り組みの背景・目指したゴール")
    lines.append("3. **行動**：自分が主体的に取った具体的な行動（何を・なぜ・どう工夫したか）")
    lines.append("4. **結果**：数字で示せる成果を必ず含める")
    lines.append("5. **学び**：そこから得た気づき・今後への活かし方")
    lines.append("")

    lines.append("### タイプ3：志望動機")
    lines.append("1. **原体験**：志望の原点となった具体的な経験や出来事")
    lines.append("2. **一般化**：その経験から得た価値観・信念・問い")
    lines.append("3. **企業固有の取り組みとの接続**：なぜ他社ではなくこの企業なのか（事業・理念・具体施策を根拠に）")
    lines.append("4. **なぜこの職種か**：志望職種でなければならない理由を明示する（隣接職種ではなくこの職種を選ぶ理由）")
    lines.append("5. **締め（能動的な行動宣言）**：入社後に何を成し遂げるかを主体的な言葉で締めくくる")
    lines.append("")

    lines.append("### タイプ4：挫折経験")
    lines.append("1. **状況**：どのような挫折・困難だったかを具体的に")
    lines.append("2. **原因の自己分析**：なぜそうなったか、自分自身の問題点も含めて率直に分析する")
    lines.append("3. **立て直しの行動**：どう乗り越えたか、具体的な行動と工夫を述べる")
    lines.append("4. **現在への影響**：その経験が現在の自分の思考・行動にどう活きているかを示す")
    lines.append("")

    lines.append("### タイプ5：強み")
    lines.append("1. **強みの提示**：最も伝えたい強みを一言で明示する")
    lines.append("2. **裏付けエピソード**：その強みが発揮された具体的な場面（行動・結果を含む）")
    lines.append("3. **仕事での活かし方**：入社後にその強みをどう活かすかを具体的に述べる")
    lines.append("")

    lines.append("### タイプ6：強み・弱み（両方を問われる場合）")
    lines.append("- **強み**：上記タイプ5の構成で書く")
    lines.append("- **弱み**：弱みを正直に述べるだけでなく、**改善のために取っている具体的な行動**とセットで必ず書くこと")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── ミクロテクニック（Section 3） ──
    lines.append("## 【文章構築のミクロテクニック】")
    lines.append("")
    lines.append("以下のルールをすべて守って文章を書いてください。")
    lines.append("")

    lines.append("### 結論ファースト（PREP法）")
    lines.append("結論 → 理由 → エピソード → 結論 の順で書くこと。")
    lines.append("")

    lines.append("### 一文一義")
    lines.append("1文に情報を詰め込みすぎないこと。読みやすさを最優先にすること。")
    lines.append("")

    lines.append("### 数字化のルール")
    lines.append("実績を書く際は「Before → After、期間、母数」をセットで書くこと。")
    lines.append("上記【応募者プロフィール】に記載された実績の数字を使用し、存在しない数値を創作しないこと。")
    lines.append("")

    lines.append("### 受け身表現の禁止")
    lines.append("「〜を知りたい」「〜を確かめたい」で文を終わらせてはいけません。")
    lines.append("知った後にどう行動するか、どう志望度が高まるかまで書くこと。")
    lines.append("")

    lines.append("### 企業固有ワードの使い方")
    lines.append("企業研究で得たキーワードは **1〜2箇所だけ** 使用し、自分の経験の言葉に自然に溶かして使うこと。")
    lines.append("3箇所以上使うと不自然になるため避けること。")
    lines.append("")

    lines.append("### 情報の創作禁止")
    lines.append("固有名詞・数値は、上記【応募者プロフィール】と【応募情報】に記載された情報の範囲内でのみ使用すること。")
    lines.append("入力されていない情報（実在しない数値・経験・固有名詞）を創作してはいけません。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 共通指示 ──
    lines.append("## 【共通執筆指示】")
    lines.append("")

    lines.append("### 参考ESの使い方")
    lines.append("- 参考ESは**構成・熱量・文体の参考**としてのみ活用してください。")
    lines.append("- フレーズや表現を流用・丸写しすることは**絶対に避けてください**。")
    lines.append("  （採用担当者はESを大量に読んでおり、類似表現はすぐに見抜かれます。）")
    lines.append("")

    lines.append("### 文字数")
    lines.append(f"- 出力は**{s.char_limit}字以内**に収めてください。")
    lines.append(f"- 少なくとも指定文字数の**9割（{int(s.char_limit * 0.9)}字）以上**を使い切ること。")
    lines.append("")

    lines.append("### 文字数が足りない場合の対応順序（必ずこの順で対処すること）")
    lines.append("1. **既存エピソードの行動・熱量を深掘りする**（最優先）：行動の具体性・工夫・感情をより詳しく書く")
    lines.append("2. **考えの言語化を厚くする**：設問が「考え」を求めている場合、思考の過程を丁寧に展開する")
    lines.append("3. **新しいエピソードを追加する**（最終手段）：分散しやすいため、他の手段を尽くしてから検討する")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── AI自己チェック（Section 4） ──
    lines.append("## 【生成後の自己点検】")
    lines.append("")
    lines.append("回答を作成したら、以下の観点をすべて確認し、満たしていない項目があれば**修正してから最終出力**してください。")
    lines.append("")
    lines.append("- [ ] 「なぜこの職種か」（隣接職種ではなくこの職種を選ぶ理由）が文章中に明示されているか")
    lines.append("- [ ] 締めの文が「〜を知りたい」「〜に貢献できればと思います」などの受け身・願望表現で終わっていないか")
    lines.append("- [ ] 複数のエピソードを使う場合、学びの結論が毎回同じフレーズに強引に着地していないか")
    lines.append("- [ ] 参照した内定者ESとフレーズが一字一句同じ箇所がないか")
    lines.append(f"- [ ] 文字数が指定の9割（{int(s.char_limit * 0.9)}字）以上あるか")
    lines.append("- [ ] 弱みを書く場合、改善のための具体的な行動がセットで書かれているか")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── タイプ判断委任 ──
    lines.append("## 【設問タイプの判断と執筆】")
    lines.append("")
    lines.append("上記6種類のフレームワーク（自己PR／ガクチカ／志望動機／挫折経験／強み／強み・弱み）のうち、")
    lines.append("**この設問文が最も当てはまるタイプをあなた自身が判断した上で、該当するフレームワークに沿ってエントリーシートの回答を作成してください。**")
    lines.append("")
    lines.append("回答の冒頭に「【判断したタイプ：◯◯】」と一行明記してから、本文を書いてください。")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════
st.title("✏️ ESプロンプトビルダー")
st.caption("入力した情報をもとに、Claude.ai に貼り付けられる完成プロンプトを生成します。AI API への接続は一切行いません。")

tab_profile, tab_application, tab_prompt, tab_history = st.tabs([
    "👤 プロフィール", "🏢 応募情報", "📋 プロンプト生成", "📊 使用履歴"
])


# ════════ TAB 1：プロフィール ═══════════════════════════════════════
with tab_profile:
    st.subheader("基本情報")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.name = st.text_input("氏名", value=st.session_state.name, placeholder="山田 太郎")
    with col2:
        st.session_state.university = st.text_input(
            "大学・学部・学年", value=st.session_state.university, placeholder="〇〇大学 〇〇学部 〇〇学科 3年"
        )

    st.divider()

    st.subheader("自己PRの軸となる強み")
    st.caption("強みをひとつずつ追加します。")

    new_strength = st.text_input("強みを入力して追加", key="new_strength_input", placeholder="例：課題発見力")
    if st.button("＋ 追加", key="add_strength"):
        val = st.session_state.new_strength_input.strip()
        if val and val not in st.session_state.strengths:
            st.session_state.strengths.append(val)
            st.rerun()

    if st.session_state.strengths:
        cols = st.columns(min(len(st.session_state.strengths), 5))
        to_remove = None
        for i, s_val in enumerate(st.session_state.strengths):
            with cols[i % 5]:
                if st.button(f"✕ {s_val}", key=f"del_strength_{i}"):
                    to_remove = i
        if to_remove is not None:
            st.session_state.strengths.pop(to_remove)
            st.rerun()
    else:
        st.info("強みがまだ登録されていません。")

    st.divider()

    st.subheader("ガクチカ（学生時代に力を入れたこと）")
    st.caption("エピソードを複数登録できます。5項目に分けて入力してください。")

    for i, ep in enumerate(st.session_state.gakuchikas):
        with st.expander(f"エピソード {i + 1}", expanded=(i == 0)):
            ep["situation"] = st.text_area("状況", value=ep.get("situation", ""),
                placeholder="例：大学1年から所属するテニスサークルで副代表を務めた。", key=f"ep_situation_{i}", height=80)
            ep["challenge"] = st.text_area("課題", value=ep.get("challenge", ""),
                placeholder="例：部員の練習参加率が低下し、大会成績が3年ぶりに地区最下位になった。", key=f"ep_challenge_{i}", height=80)
            ep["action"] = st.text_area("行動", value=ep.get("action", ""),
                placeholder="例：個別ヒアリングを実施し、初心者向け練習メニューを新設。SNS告知を週3回に増やした。", key=f"ep_action_{i}", height=100)
            ep["result"] = st.text_area("結果（数字を含めて）", value=ep.get("result", ""),
                placeholder="例：3か月で参加率が42%→78%に向上。翌年の地区大会で準優勝。", key=f"ep_result_{i}", height=80)
            ep["learning"] = st.text_area("学び", value=ep.get("learning", ""),
                placeholder="例：課題の根本を掘り下げてから施策を設計することの重要性を学んだ。", key=f"ep_learning_{i}", height=80)
            if len(st.session_state.gakuchikas) > 1:
                if st.button("このエピソードを削除", key=f"del_ep_{i}"):
                    st.session_state.gakuchikas.pop(i)
                    st.rerun()

    if st.button("＋ エピソードを追加"):
        st.session_state.gakuchikas.append({"situation": "", "challenge": "", "action": "", "result": "", "learning": ""})
        st.rerun()

    st.divider()

    st.subheader("実績の数字")
    st.caption("Before / After・期間・母数のセットで登録します。")

    for i, ach in enumerate(st.session_state.achievements):
        with st.expander(f"実績 {i + 1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                ach["before"] = st.text_input("Before", value=ach.get("before", ""), placeholder="例：売上 月50万円", key=f"ach_before_{i}")
            with c2:
                ach["after"] = st.text_input("After", value=ach.get("after", ""), placeholder="例：売上 月120万円", key=f"ach_after_{i}")
            c3, c4 = st.columns(2)
            with c3:
                ach["period"] = st.text_input("期間", value=ach.get("period", ""), placeholder="例：6か月", key=f"ach_period_{i}")
            with c4:
                ach["scale"] = st.text_input("母数", value=ach.get("scale", ""), placeholder="例：部員30人中", key=f"ach_scale_{i}")
            if len(st.session_state.achievements) > 1:
                if st.button("この実績を削除", key=f"del_ach_{i}"):
                    st.session_state.achievements.pop(i)
                    st.rerun()

    if st.button("＋ 実績を追加"):
        st.session_state.achievements.append({"before": "", "after": "", "period": "", "scale": ""})
        st.rerun()

    st.divider()

    st.subheader("プロフィールの保存・読み込み")
    col_save, col_load = st.columns(2)

    with col_save:
        profile_json = json.dumps(profile_to_dict(), ensure_ascii=False, indent=2)
        st.download_button(
            label="💾 プロフィールを保存（JSONダウンロード）",
            data=profile_json,
            file_name="es_profile.json",
            mime="application/json",
            use_container_width=True,
        )

    with col_load:
        uploaded = st.file_uploader("📂 プロフィールを読み込む（JSON）", type="json", key="profile_upload")
        if uploaded is not None:
            try:
                data = json.load(uploaded)
                load_profile(data)
                st.success("プロフィールを読み込みました。")
                st.rerun()
            except Exception as e:
                st.error(f"読み込みに失敗しました：{e}")


# ════════ TAB 2：応募情報 ═══════════════════════════════════════════
with tab_application:
    st.subheader("応募企業・設問の情報")

    col1, col2 = st.columns(2)
    with col1:
        st.session_state.company = st.text_input("企業名", value=st.session_state.company, placeholder="例：株式会社〇〇")
    with col2:
        st.session_state.industry = st.text_input(
            "業界・職種", value=st.session_state.industry, placeholder="例：IT／コンサルティング業界・法人営業職"
        )

    st.session_state.question = st.text_area(
        "ES設問文", value=st.session_state.question,
        placeholder="例：学生時代に最も力を入れたことを教えてください。", height=100,
    )

    st.session_state.char_limit = st.number_input(
        "文字数指定（字以内）", min_value=50, max_value=3000,
        value=st.session_state.char_limit, step=50,
    )

    st.divider()
    st.subheader("参照する内定者ES")
    st.caption("内定者ESのテキストを貼り付けてください。構成・熱量の参考としてプロンプトに含めます。")

    for i, ref in enumerate(st.session_state.reference_es_list):
        st.session_state.reference_es_list[i] = st.text_area(
            f"内定者ES {i + 1}", value=ref, height=150,
            placeholder="内定者のESをここに貼り付けてください。", key=f"ref_es_{i}",
        )
        if len(st.session_state.reference_es_list) > 1:
            if st.button("この例文を削除", key=f"del_ref_{i}"):
                st.session_state.reference_es_list.pop(i)
                st.rerun()

    if st.button("＋ 内定者ESを追加"):
        st.session_state.reference_es_list.append("")
        st.rerun()

    st.divider()
    st.subheader("企業研究メモ・キーワード（任意）")
    st.session_state.research_notes = st.text_area(
        "企業が使うキーワード、OB/OG訪問メモ、ニュースメモなど",
        value=st.session_state.research_notes, height=120,
        placeholder="例：「共創」「社会インフラ」「DX推進」 / 中期経営計画でXX事業を強化中 / OB談：〇〇という価値観を大切にしている",
    )


# ════════ TAB 3：プロンプト生成 ═════════════════════════════════════
with tab_prompt:
    st.subheader("プロンプトを生成する")

    warnings_list = []
    if not st.session_state.name:
        warnings_list.append("氏名が未入力です（プロフィールタブ）")
    if not st.session_state.question:
        warnings_list.append("ES設問文が未入力です（応募情報タブ）")
    if not st.session_state.company:
        warnings_list.append("企業名が未入力です（応募情報タブ）")

    for w in warnings_list:
        st.warning(f"⚠️ {w}")

    if st.session_state.question:
        guessed = guess_question_type(st.session_state.question)
        if guessed:
            st.info(f"参考：おそらく **{guessed}** タイプと思われます（最終判断はClaudeに委ねます）")

    if st.button("🚀 プロンプトを生成", type="primary", use_container_width=True):
        st.session_state["generated_prompt"] = build_prompt()
        if st.session_state.company:
            save_history(build_history_entry())

    if st.session_state.get("generated_prompt"):
        prompt_text = st.session_state["generated_prompt"]
        st.success(f"プロンプトが生成されました（{len(prompt_text):,}文字）")
        st.caption("下のコードブロック右上のコピーアイコンをクリックして全文コピーし、Claude.ai に貼り付けてください。")
        st.code(prompt_text, language=None)

        st.divider()
        st.subheader("使い方")
        st.markdown("""
1. 上のプロンプトを **全文コピー** します
2. [Claude.ai](https://claude.ai/) を開き、新しいチャットを始めます
3. プロンプトを貼り付けて送信します
4. Claudeが返答した内容を確認し、必要に応じて「〇〇の部分をもっと具体的に」などと追加指示してブラッシュアップします
""")

    st.divider()
    st.subheader("📝 セルフチェック")
    st.caption("ClaudeのESを貼り付けると、文字数・受け身表現・実績数字の整合をルールベースでチェックします。")

    es_input = st.text_area(
        "生成されたESの本文をここに貼り付けてください",
        height=200,
        placeholder="Claudeが出力したESの本文をここに貼り付けてください…",
        key="es_check_input",
    )

    if st.button("チェックを実行", key="run_check"):
        if es_input.strip():
            results = check_es_text(es_input.strip(), st.session_state.char_limit, st.session_state.achievements)
            for r in results:
                icon = "✅" if r["status"] == "ok" else "⚠️"
                if r["status"] == "ok":
                    st.success(f"{icon} **{r['label']}**：{r['message']}")
                else:
                    st.warning(f"{icon} **{r['label']}**：{r['message']}")
        else:
            st.error("ES本文を入力してください。")


# ════════ TAB 4：使用履歴 ═══════════════════════════════════════════
with tab_history:
    st.subheader("使用履歴")
    st.caption("プロンプト生成のたびに自動記録されます（企業名が入力されている場合のみ）。")

    history = load_history()

    if not history:
        st.info("履歴はまだありません。プロンプトを生成すると自動記録されます。")
    else:
        if st.button("🗑️ 履歴をすべて削除", key="clear_history"):
            HISTORY_FILE.unlink(missing_ok=True)
            st.success("履歴を削除しました。")
            st.rerun()

        for entry in reversed(history):
            with st.expander(f"📌 {entry.get('timestamp', '')}　{entry.get('company', '')}　「{entry.get('question', '')}」", expanded=False):
                st.markdown(f"**企業名：** {entry.get('company', '')}")
                st.markdown(f"**設問：** {entry.get('question', '')}")
                st.markdown(f"**文字数：** {entry.get('char_limit', '')}字以内")
                if entry.get("used_gakuchikas"):
                    st.markdown("**使用したガクチカ：**")
                    for ep in entry["used_gakuchikas"]:
                        st.markdown(f"- {ep}…")
                if entry.get("used_numbers"):
                    st.markdown(f"**使用した数字：** {' / '.join(entry['used_numbers'])}")
                if entry.get("used_keywords"):
                    st.markdown(f"**使用したキーワード：** {' / '.join(entry['used_keywords'])}")
