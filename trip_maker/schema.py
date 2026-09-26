"""行き先データのスキーマと検証。

行き先 1 件は次の形の dict。金額はすべて円、時間はすべて「時間（小数）」。

    {
        "id": "onomichi",                  # 英小文字・数字・_ のみ。全データで一意
        "name": "尾道・しまなみ海道",
        "pref": "広島県",                  # 海外は国名（例："台湾"）
        "region": "chugoku",               # constants.REGIONS のキー
        "niche": 3,                        # 1=超王道 … 5=超ニッチ（constants.NICHE_LABELS）
        "genres": {"town": 3, "nature": 2, ...},   # constants.GENRES のキー → 強さ 1〜3
        "tagline": "坂と猫の町から、瀬戸内の島々を自転車で渡る",   # 40字程度
        "description": "2〜3文の紹介",
        "best_months": [3, 4, 5, 10, 11],  # 特におすすめの月（1〜12）
        "avoid_months": [],                # 行くのが現実的でない月（道路閉鎖・運休など）
        "min_nights": 0,                   # 最低限必要な泊数（0 = 日帰りも可）
        "ideal_nights": [1, 2],            # ちょうどよい泊数の [下限, 上限]
        "fit": {"solo": 3, "friends": 3, "couple": 3,
                "family_kids": 2, "family_adults": 2, "group": 2},  # 関係性ごとの相性 0〜3
        "price_level": 1.0,                # 現地の物価（飲食）の倍率。全国平均 = 1.0
        "access": {                        # constants.HUBS の各キー → 行き方の候補 1〜2 件
            "tokyo": [
                {"mode": "rail",           # constants.ACCESS_MODES のキー（主な手段）
                 "route": "東京→（のぞみ）→福山→（JR山陽本線）→尾道",
                 "hours": 4.0,             # ハブ中心部から現地中心部までの片道所要（乗換・空港手続き込み）
                 "cost": 17000},           # 大人 1 名・片道・通常期の目安
                # 任意: "overnight": True  # 夜行バス・夜行フェリー等で車中/船中 1 泊を含む
                #                          # （その夜の宿代は運賃に含まれる扱い）
            ],
            ...
        },
        "local_transport": {
            "note": "徒歩＋レンタサイクル＋路線バス",
            "cost_per_day": 1500,          # 1 人 1 日あたり
            "car": False,                  # True ならレンタカー前提（cost_per_day は無視され車代で計算）
        },
        "lodging": {                       # 3 段階すべて必須
            "budget":   {"type": "ゲストハウス・ビジネスホテル", "price": 6000, "meals": 0},
            "standard": {"type": "シティホテル・町家の宿", "price": 12000, "meals": 1},
            "premium":  {"type": "オーベルジュ・高級旅館", "price": 30000, "meals": 2},
        },                                 # price = 2 名 1 室利用時の 1 人 1 泊あたり（通常期）
                                           # meals = 0 素泊まり / 1 朝食付き / 2 朝夕 2 食付き
        "foods": [                         # 名物・食べたいもの 4〜8 件
            {"name": "尾道ラーメン", "price": 900, "meal": "lunch",
             "note": "背脂が浮く醤油スープ"},
            ...
        ],
        "spots": [                         # 見どころ 10〜16 件
            {"name": "千光寺",
             "area": "尾道市街",           # 同じ日にまとめて回れる単位のエリア名
             "kind": "temple",             # constants.SPOT_KINDS のキー
             "genres": ["history", "nature"],
             "niche": 2,                   # スポット単位の王道〜ニッチ度 1〜5
             "hours": 1.5,                 # 滞在の目安
             "cost": 0,                    # 大人 1 名の入場・体験料
             "when": ["morning", "day"],   # constants.TIMES_OF_DAY のキー（1 つ以上）
             "indoor": False,              # 雨でも楽しめるなら True
             "fit": ["couple", "solo"],    # 特に向いている関係性（空でも可）
             "note": "ロープウェイで山頂へ。尾道水道を一望",
             # 任意: "months": [4, 5]      # 特定の月しか成立しないスポット
             # 任意: "avoid": ["family_kids"]  # 向かない関係性
             # 任意: "booking": True       # 事前予約がほぼ必須
             # 任意: "closed": [0]         # 定休日（0=月 … 6=日）。祝日の振替などは note に書く
            },
            ...
        ],
        "tips": ["一言アドバイス", ...],   # 1〜4 件
        "nearby": [                        # 任意。組み合わせて周遊しやすい別の行き先
            {"id": "kurashiki", "hours": 1.0, "cost": 1500, "route": "尾道→（JR）→倉敷"},
        ],
        # 海外のみ必須:
        # "notes_overseas": "パスポート必須。90日以内の観光はビザ不要…",
        # 海外でも access は 8 ハブすべて必須（直行便がなければ乗継ぎで記述）
        # 任意: "tz_offset": -2      # 現地時間 − 日本時間（時間）。旅程の到着・出発時刻に使う
    }
"""

from __future__ import annotations

import re

from .constants import (
    ACCESS_MODES,
    GENRES,
    HUBS,
    LODGING_MEALS_LABELS,
    LODGING_TIERS,
    MEALS,
    NICHE_LABELS,
    REGIONS,
    RELATIONS,
    SPOT_KINDS,
    TIMES_OF_DAY,
)

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

REQUIRED_KEYS = (
    "id", "name", "pref", "region", "niche", "genres", "tagline", "description",
    "best_months", "avoid_months", "min_nights", "ideal_nights", "fit", "price_level",
    "access", "local_transport", "lodging", "foods", "spots", "tips",
)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_months(value, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or any(not isinstance(m, int) or not 1 <= m <= 12 for m in value):
        errors.append(f"{label} は 1〜12 の整数リストにしてください")


def validate_destination(d: dict) -> list[str]:
    """行き先 1 件を検証し、問題点のリストを返す（空なら OK）。"""
    errors: list[str] = []
    did = d.get("id", "?")

    def err(msg: str) -> None:
        errors.append(f"[{did}] {msg}")

    for key in REQUIRED_KEYS:
        if key not in d:
            err(f"必須キー {key} がありません")
    if errors:
        return errors

    if not isinstance(d["id"], str) or not _ID_RE.match(d["id"]):
        err("id は英小文字で始まる英小文字・数字・_ の文字列にしてください")
    for key in ("name", "pref", "tagline", "description"):
        if not isinstance(d[key], str) or not d[key].strip():
            err(f"{key} は空でない文字列にしてください")
    if d["region"] not in REGIONS:
        err(f"region が不正です: {d['region']}")
    if d["niche"] not in NICHE_LABELS:
        err(f"niche は 1〜5 にしてください: {d['niche']}")

    genres = d["genres"]
    if not isinstance(genres, dict) or not genres:
        err("genres は空でない dict にしてください")
    else:
        for g, v in genres.items():
            if g not in GENRES:
                err(f"未知のジャンル: {g}")
            if v not in (1, 2, 3):
                err(f"ジャンル {g} の強さは 1〜3 にしてください: {v}")

    _check_months(d["best_months"], "best_months", errors)
    _check_months(d["avoid_months"], "avoid_months", errors)
    if isinstance(d["best_months"], list) and isinstance(d["avoid_months"], list):
        overlap = set(d["best_months"]) & set(d["avoid_months"])
        if overlap:
            err(f"best_months と avoid_months が重なっています: {sorted(overlap)}")
        if len(set(d["avoid_months"])) >= 12:
            err("avoid_months が 12 か月すべてになっています")

    if not isinstance(d["min_nights"], int) or d["min_nights"] < 0:
        err("min_nights は 0 以上の整数にしてください")
    ideal = d["ideal_nights"]
    if (not isinstance(ideal, list) or len(ideal) != 2
            or any(not isinstance(n, int) for n in ideal) or ideal[0] > ideal[1]):
        err("ideal_nights は [下限, 上限] の整数 2 要素にしてください")
    elif isinstance(d["min_nights"], int) and ideal[0] < d["min_nights"]:
        err("ideal_nights の下限が min_nights より小さくなっています")

    fit = d["fit"]
    if not isinstance(fit, dict) or set(fit) != set(RELATIONS):
        err(f"fit には {list(RELATIONS)} のすべてのキーが必要です")
    else:
        for r, v in fit.items():
            if v not in (0, 1, 2, 3):
                err(f"fit[{r}] は 0〜3 にしてください: {v}")

    if not _is_num(d["price_level"]) or not 0.5 <= d["price_level"] <= 2.5:
        err(f"price_level は 0.5〜2.5 の数値にしてください: {d['price_level']}")

    # ── access ──
    access = d["access"]
    is_overseas = d["region"] == "overseas"
    if not isinstance(access, dict):
        err("access は dict にしてください")
    else:
        missing = set(HUBS) - set(access)
        if missing:
            err(f"access に不足しているハブがあります: {sorted(missing)}")
        for hub, options in access.items():
            if hub not in HUBS:
                err(f"未知のハブ: {hub}")
                continue
            if not isinstance(options, list) or not 1 <= len(options) <= 3:
                err(f"access[{hub}] は 1〜3 件のリストにしてください")
                continue
            for opt in options:
                if opt.get("mode") not in ACCESS_MODES:
                    err(f"access[{hub}] の mode が不正です: {opt.get('mode')}")
                if not isinstance(opt.get("route"), str) or not opt.get("route"):
                    err(f"access[{hub}] に route がありません")
                if not _is_num(opt.get("hours")) or not 0 < opt["hours"] <= 30:
                    err(f"access[{hub}] の hours が不正です: {opt.get('hours')}")
                if not _is_num(opt.get("cost")) or not 0 <= opt["cost"] <= 400000:
                    err(f"access[{hub}] の cost が不正です: {opt.get('cost')}")
                if "overnight" in opt and not isinstance(opt["overnight"], bool):
                    err(f"access[{hub}] の overnight は bool にしてください")

    # ── local_transport ──
    lt = d["local_transport"]
    if not isinstance(lt, dict) or not isinstance(lt.get("note"), str):
        err("local_transport.note がありません")
    elif not _is_num(lt.get("cost_per_day")) or lt["cost_per_day"] < 0 or not isinstance(lt.get("car"), bool):
        err("local_transport の cost_per_day（数値）/ car（bool）が不正です")

    # ── lodging ──
    lodging = d["lodging"]
    if not isinstance(lodging, dict) or set(lodging) != set(LODGING_TIERS):
        err(f"lodging には {list(LODGING_TIERS)} の 3 段階が必要です")
    else:
        prices = []
        for tier in LODGING_TIERS:
            lo = lodging[tier]
            if not isinstance(lo.get("type"), str) or not lo.get("type"):
                err(f"lodging[{tier}].type がありません")
            if not _is_num(lo.get("price")) or not 1500 <= lo["price"] <= 300000:
                err(f"lodging[{tier}].price が不正です: {lo.get('price')}")
            else:
                prices.append(lo["price"])
            if lo.get("meals") not in LODGING_MEALS_LABELS:
                err(f"lodging[{tier}].meals は 0/1/2 にしてください")
        if len(prices) == 3 and not prices[0] <= prices[1] <= prices[2]:
            err("lodging の価格は budget ≤ standard ≤ premium にしてください")

    # ── foods ──
    foods = d["foods"]
    if not isinstance(foods, list) or not 3 <= len(foods) <= 12:
        err("foods は 3〜12 件にしてください")
    else:
        for f in foods:
            if not f.get("name"):
                err("foods に name のない要素があります")
            if not _is_num(f.get("price")) or not 0 < f["price"] <= 50000:
                err(f"foods[{f.get('name')}].price が不正です")
            if f.get("meal") not in MEALS:
                err(f"foods[{f.get('name')}].meal が不正です: {f.get('meal')}")
            if not isinstance(f.get("note", ""), str):
                err(f"foods[{f.get('name')}].note は文字列にしてください")

    # ── spots ──
    spots = d["spots"]
    if not isinstance(spots, list) or not 8 <= len(spots) <= 24:
        err("spots は 8〜24 件にしてください")
    else:
        names = set()
        for s in spots:
            sname = s.get("name", "?")
            if sname in names:
                err(f"spots の名前が重複しています: {sname}")
            names.add(sname)
            for key in ("name", "area", "note"):
                if not isinstance(s.get(key), str) or not s.get(key):
                    err(f"spots[{sname}].{key} がありません")
            if s.get("kind") not in SPOT_KINDS:
                err(f"spots[{sname}].kind が不正です: {s.get('kind')}")
            sg = s.get("genres")
            if not isinstance(sg, list) or not sg or any(g not in GENRES for g in sg):
                err(f"spots[{sname}].genres が不正です: {sg}")
            if s.get("niche") not in NICHE_LABELS:
                err(f"spots[{sname}].niche は 1〜5 にしてください")
            if not _is_num(s.get("hours")) or not 0.25 <= s["hours"] <= 10:
                err(f"spots[{sname}].hours が不正です: {s.get('hours')}")
            if not _is_num(s.get("cost")) or not 0 <= s["cost"] <= 100000:
                err(f"spots[{sname}].cost が不正です: {s.get('cost')}")
            when = s.get("when")
            if not isinstance(when, list) or not when or any(w not in TIMES_OF_DAY for w in when):
                err(f"spots[{sname}].when が不正です: {when}")
            if not isinstance(s.get("indoor"), bool):
                err(f"spots[{sname}].indoor は bool にしてください")
            sfit = s.get("fit", [])
            if not isinstance(sfit, list) or any(r not in RELATIONS for r in sfit):
                err(f"spots[{sname}].fit が不正です: {sfit}")
            avoid = s.get("avoid", [])
            if not isinstance(avoid, list) or any(r not in RELATIONS for r in avoid):
                err(f"spots[{sname}].avoid が不正です: {avoid}")
            if "months" in s:
                _check_months(s["months"], f"[{did}] spots[{sname}].months", errors)
            closed = s.get("closed", [])
            if not isinstance(closed, list) or any(not isinstance(w, int) or not 0 <= w <= 6 for w in closed) \
                    or len(set(closed)) >= 7:
                err(f"spots[{sname}].closed は 0〜6 の整数リスト（全曜日は不可）にしてください")
            if "booking" in s and not isinstance(s["booking"], bool):
                err(f"spots[{sname}].booking は bool にしてください")
        if len({s.get("area") for s in spots}) < 2 and d["region"] != "overseas":
            pass  # エリアが 1 つでも許容（小さな島など）

    tips = d["tips"]
    if not isinstance(tips, list) or not 1 <= len(tips) <= 6 or any(not isinstance(t, str) for t in tips):
        err("tips は 1〜6 件の文字列リストにしてください")

    nearby = d.get("nearby", [])
    if not isinstance(nearby, list):
        err("nearby はリストにしてください")
    else:
        for n in nearby:
            if not isinstance(n.get("id"), str):
                err("nearby の要素に id がありません")
            if not _is_num(n.get("hours")) or not _is_num(n.get("cost")):
                err(f"nearby[{n.get('id')}] の hours / cost が不正です")
            if not isinstance(n.get("route"), str):
                err(f"nearby[{n.get('id')}] に route がありません")

    if "tz_offset" in d and (not _is_num(d["tz_offset"]) or not -23 <= d["tz_offset"] <= 23):
        err("tz_offset は -23〜23 の数値にしてください")
    if is_overseas and not isinstance(d.get("notes_overseas"), str):
        err("海外の行き先には notes_overseas（パスポート・ビザ・通貨など）が必要です")

    return errors


def validate_all(destinations: list[dict]) -> list[str]:
    """全行き先を検証する。id の重複と nearby の参照切れも確認する。"""
    errors: list[str] = []
    ids: set[str] = set()
    for d in destinations:
        errors.extend(validate_destination(d))
        did = d.get("id")
        if did in ids:
            errors.append(f"[{did}] id が重複しています")
        ids.add(did)
    for d in destinations:
        for n in d.get("nearby", []) or []:
            if n.get("id") not in ids:
                errors.append(f"[{d.get('id')}] nearby の参照先が存在しません: {n.get('id')}")
            if n.get("id") == d.get("id"):
                errors.append(f"[{d.get('id')}] nearby に自分自身が含まれています")
    return errors
