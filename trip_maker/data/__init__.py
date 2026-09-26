"""行き先データ。地域ごとのモジュールが DESTINATIONS（dict のリスト）を公開する。

スキーマは trip_maker/schema.py を参照。
"""

from __future__ import annotations

import importlib

# 地域モジュール名（trip_maker/data/<name>.py）
REGION_MODULES = (
    "hokkaido",
    "tohoku",
    "kanto",
    "chubu_north",
    "chubu_tokai",
    "kinki_north",
    "kinki_south",
    "chugoku",
    "shikoku",
    "kyushu_north",
    "kyushu_south",
    "okinawa",
    "overseas_north",
    "overseas_south",
)

# データの確認状況（2026 年 9 月の作成時）。セッションの Web 検索上限に達したため、
# 後半に作成したモジュールは Web で確認できていない。画面とダウンロードに表示する。
DATA_BASIS_LABELS = {
    "web_partial": "主な運賃・料金の一部を 2026 年 9 月に Web 検索で確認（残りは推定）",
    "knowledge": "Web では未確認（2026 年 6 月までの知識に基づく推定値）",
}
MODULE_DATA_BASIS = {
    "hokkaido": "web_partial",
    "tohoku": "web_partial",
    "kanto": "knowledge",
    "chubu_north": "web_partial",
    "chubu_tokai": "web_partial",
    "kinki_north": "knowledge",
    "kinki_south": "web_partial",
    "chugoku": "web_partial",
    "shikoku": "knowledge",
    "kyushu_north": "web_partial",
    "kyushu_south": "web_partial",
    "okinawa": "knowledge",
    "overseas_north": "knowledge",
    "overseas_south": "knowledge",
}

_cache: list[dict] | None = None


def load_destinations(strict: bool = True) -> list[dict]:
    """すべての地域モジュールから行き先を読み込む。

    strict=False のときは存在しないモジュールを飛ばす（データ作成途中の開発用）。
    """
    global _cache
    if _cache is not None and strict:
        return _cache
    destinations: list[dict] = []
    for name in REGION_MODULES:
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as e:
            if strict or e.name != f"{__name__}.{name}":
                raise
            continue
        for d in module.DESTINATIONS:
            d.setdefault("data_basis", MODULE_DATA_BASIS[name])
        destinations.extend(module.DESTINATIONS)
    if strict:
        _cache = destinations
    return destinations
