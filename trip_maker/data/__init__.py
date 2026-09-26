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
        destinations.extend(module.DESTINATIONS)
    if strict:
        _cache = destinations
    return destinations
