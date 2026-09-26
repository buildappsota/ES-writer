"""テスト用の固定データ（実データとは独立）。

数値は検証用のダミーで、実際の運賃・料金を表すものではない。
"""

import copy

ONOMICHI = {
    "id": "onomichi_shimanami",
    "name": "尾道・しまなみ海道",
    "pref": "広島県",
    "region": "chugoku",
    "niche": 3,
    "genres": {"town": 3, "nature": 2, "activity": 3, "gourmet": 2, "art": 2, "history": 1},
    "tagline": "坂と猫の町から、瀬戸内の島々を自転車で渡る",
    "description": "寺と坂道が折り重なる尾道の古い町並みを歩き、翌日はしまなみ海道で島から島へ。サイクリングの聖地として国内外から人が集まる。",
    "best_months": [3, 4, 5, 10, 11],
    "avoid_months": [],
    "min_nights": 0,
    "ideal_nights": [1, 2],
    "fit": {"solo": 3, "friends": 3, "couple": 3, "family_kids": 1, "family_adults": 2, "group": 2},
    "price_level": 0.95,
    "access": {
        "tokyo": [
            {"mode": "rail", "route": "東京→（のぞみ）→福山→（JR山陽本線）→尾道", "hours": 4.0, "cost": 17500},
            {"mode": "flight", "route": "羽田→（飛行機）→広島空港→（バス）→尾道", "hours": 3.8, "cost": 16000},
        ],
        "sendai": [
            {"mode": "rail", "route": "仙台→（はやぶさ）→東京→（のぞみ）→福山→尾道", "hours": 6.8, "cost": 28500},
        ],
        "sapporo": [
            {"mode": "flight", "route": "新千歳→（飛行機）→広島空港→（バス）→尾道", "hours": 4.3, "cost": 30000},
        ],
        "nagoya": [
            {"mode": "rail", "route": "名古屋→（のぞみ）→福山→（JR山陽本線）→尾道", "hours": 2.7, "cost": 12500},
        ],
        "osaka": [
            {"mode": "rail", "route": "新大阪→（のぞみ・さくら）→福山→（JR山陽本線）→尾道", "hours": 1.7, "cost": 8500},
            {"mode": "bus", "route": "大阪→（高速バス）→尾道", "hours": 4.5, "cost": 4500},
        ],
        "hiroshima": [
            {"mode": "rail", "route": "広島→（JR山陽本線）→尾道", "hours": 1.3, "cost": 1700},
        ],
        "fukuoka": [
            {"mode": "rail", "route": "博多→（のぞみ・さくら）→福山→（JR山陽本線）→尾道", "hours": 2.0, "cost": 11500},
        ],
        "naha": [
            {"mode": "flight", "route": "那覇→（飛行機）→広島空港→（バス）→尾道", "hours": 3.8, "cost": 25000},
        ],
    },
    "local_transport": {"note": "市街は徒歩。島へはレンタサイクル・路線バス・渡船", "cost_per_day": 1500, "car": False},
    "lodging": {
        "budget": {"type": "ゲストハウス・ビジネスホテル", "price": 5500, "meals": 0},
        "standard": {"type": "シティホテル・古民家の宿", "price": 12000, "meals": 1},
        "premium": {"type": "サイクリスト向けデザインホテル・島の高級旅館", "price": 30000, "meals": 2},
    },
    "foods": [
        {"name": "尾道ラーメン", "price": 900, "meal": "lunch", "note": "背脂が浮く醤油スープに平打ち麺"},
        {"name": "瀬戸内の魚の刺身・煮付け", "price": 3500, "meal": "dinner", "note": "小イワシやタコなど地魚"},
        {"name": "レモンケーキ・レモンスイーツ", "price": 500, "meal": "snack", "note": "瀬戸田は国産レモンの産地"},
        {"name": "はっさく大福", "price": 300, "meal": "snack", "note": "因島の名物"},
        {"name": "たこ飯", "price": 1500, "meal": "lunch", "note": "三原・しまなみ周辺のタコ"},
    ],
    "spots": [
        {"name": "千光寺と千光寺公園", "area": "尾道市街", "kind": "temple", "genres": ["history", "nature"], "niche": 2,
         "hours": 1.5, "cost": 0, "when": ["morning", "day"], "indoor": False, "fit": ["couple", "solo"],
         "note": "ロープウェイで山頂へ上がり、坂を下りながら尾道水道を一望"},
        {"name": "猫の細道", "area": "尾道市街", "kind": "sight", "genres": ["town"], "niche": 3,
         "hours": 0.5, "cost": 0, "when": ["morning", "day"], "indoor": False, "fit": ["solo", "couple"],
         "note": "猫と小さな店が点在する路地"},
        {"name": "尾道本通り商店街", "area": "尾道市街", "kind": "shopping", "genres": ["town", "gourmet"], "niche": 2,
         "hours": 1.0, "cost": 0, "when": ["day", "evening"], "indoor": True, "fit": [],
         "note": "駅前から東へ続くアーケード。古い商家と新しい店が混在"},
        {"name": "ONOMICHI U2", "area": "尾道市街", "kind": "shopping", "genres": ["art", "town"], "niche": 3,
         "hours": 1.0, "cost": 0, "when": ["day", "evening"], "indoor": True, "fit": ["couple", "friends"],
         "note": "海運倉庫を改装したサイクリスト向け複合施設"},
        {"name": "尾道市立美術館", "area": "尾道市街", "kind": "museum", "genres": ["art"], "niche": 3,
         "hours": 1.0, "cost": 1000, "when": ["day"], "indoor": True, "fit": ["solo", "family_adults"],
         "note": "安藤忠雄が改修を手がけた千光寺公園内の美術館（料金は展示により変動）"},
        {"name": "しまなみ海道サイクリング（尾道〜生口島）", "area": "しまなみ海道", "kind": "activity",
         "genres": ["activity", "nature"], "niche": 2, "hours": 5.0, "cost": 3000, "when": ["morning", "day"],
         "indoor": False, "fit": ["friends", "couple", "solo"],
         "note": "レンタサイクルで向島・因島・生口島へ。橋からの多島美が見どころ（料金は貸出料と保証料の目安）"},
        {"name": "耕三寺博物館と未来心の丘", "area": "しまなみ海道", "kind": "museum", "genres": ["art", "history"],
         "niche": 3, "hours": 1.5, "cost": 1400, "when": ["day"], "indoor": False, "fit": ["couple", "friends"],
         "note": "生口島の寺院博物館と、大理石でできた白い庭園"},
        {"name": "瀬戸田しおまち商店街", "area": "しまなみ海道", "kind": "market", "genres": ["town", "gourmet"],
         "niche": 3, "hours": 1.0, "cost": 0, "when": ["day"], "indoor": False, "fit": [],
         "note": "レモンスイーツやタコ料理の店が並ぶ島の商店街"},
        {"name": "因島水軍城", "area": "しまなみ海道", "kind": "museum", "genres": ["history"], "niche": 4,
         "hours": 1.0, "cost": 330, "when": ["day"], "indoor": True, "fit": ["solo", "family_kids"],
         "note": "村上水軍の資料館"},
        {"name": "向島の渡船で夕暮れ散歩", "area": "尾道市街", "kind": "sight", "genres": ["town", "nature"], "niche": 4,
         "hours": 1.0, "cost": 200, "when": ["evening"], "indoor": False, "fit": ["couple", "solo"],
         "note": "尾道水道を数分で渡る生活の足。対岸から見る夕景の尾道"},
    ],
    "tips": [
        "しまなみ海道を尾道から今治まで自転車で走り切ると約70km。初心者は生口島あたりで折り返すか、バスや船と組み合わせる",
        "坂と階段が多いので歩きやすい靴で",
    ],
    "nearby": [
        {"id": "kurashiki", "hours": 1.0, "cost": 1700, "route": "尾道→（JR山陽本線）→倉敷"},
    ],
}


def make_island() -> dict:
    """夜行フェリーでしか行けない離島（小笠原型）。"""
    d = copy.deepcopy(ONOMICHI)
    d.update(id="test_island", name="テスト島", pref="東京都", region="kanto", niche=5,
             genres={"remote": 3, "beach": 3, "nature": 3}, min_nights=4, ideal_nights=[5, 6],
             avoid_months=[], nearby=[])
    for hub in d["access"]:
        d["access"][hub] = [{"mode": "ferry", "route": "港→（フェリー）→テスト島", "hours": 24.0,
                             "cost": 30000, "overnight": True}]
    return d


def make_winter_closed() -> dict:
    """冬季閉鎖の山岳リゾート。"""
    d = copy.deepcopy(ONOMICHI)
    d.update(id="test_mountain", name="テスト高原", pref="長野県", region="chubu", niche=2,
             genres={"nature": 3, "onsen": 2}, best_months=[7, 8], avoid_months=[12, 1, 2, 3], nearby=[])
    return d


def make_far_flight_only() -> dict:
    """飛行機でしか行けない遠い行き先（日帰り不可）。"""
    d = copy.deepcopy(ONOMICHI)
    d.update(id="test_far", name="テスト南島", pref="沖縄県", region="okinawa", niche=4,
             genres={"beach": 3, "remote": 2}, min_nights=1, ideal_nights=[2, 3], nearby=[])
    for hub in d["access"]:
        d["access"][hub] = [{"mode": "flight", "route": "空港→（飛行機）→テスト南島空港", "hours": 5.0, "cost": 25000}]
    return d


def make_overseas() -> dict:
    d = copy.deepcopy(ONOMICHI)
    d.update(id="test_abroad", name="テスト市", pref="テスト国", region="overseas", niche=1,
             genres={"gourmet": 3, "town": 3}, min_nights=1, ideal_nights=[2, 3], nearby=[],
             notes_overseas="パスポート必須（テスト用）")
    for hub in d["access"]:
        d["access"][hub] = [{"mode": "flight", "route": "空港→（飛行機）→テスト国際空港", "hours": 5.0, "cost": 30000}]
    return d


def make_kurashiki() -> dict:
    d = copy.deepcopy(ONOMICHI)
    d.update(id="kurashiki", name="テスト倉敷", niche=2, nearby=[])
    for i, s in enumerate(d["spots"]):
        s["name"] = f"倉敷スポット{i + 1}"
    return d


def all_fixtures() -> list[dict]:
    return [copy.deepcopy(ONOMICHI), make_kurashiki(), make_island(), make_winter_closed(),
            make_far_flight_only(), make_overseas()]
