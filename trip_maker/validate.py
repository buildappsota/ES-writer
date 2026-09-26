"""行き先データの検証 CLI。

    python -m trip_maker.validate            # 全モジュール
    python -m trip_maker.validate kanto      # 指定モジュールのみ
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections import Counter

from .data import REGION_MODULES, load_destinations
from .schema import validate_all, validate_destination


def main(argv: list[str]) -> int:
    if argv:
        dests: list[dict] = []
        for name in argv:
            dests.extend(importlib.import_module(f"trip_maker.data.{name}").DESTINATIONS)
        errors = [e for d in dests for e in validate_destination(d)]
        ids = Counter(d.get("id") for d in dests)
        errors += [f"[{i}] id が重複しています" for i, c in ids.items() if c > 1]
    else:
        dests = load_destinations(strict=False)
        errors = validate_all(dests)
        missing = [m for m in REGION_MODULES
                   if importlib.util.find_spec(f"trip_maker.data.{m}") is None]
        if missing:
            print(f"（未作成のモジュール: {', '.join(missing)}）")

    for e in errors:
        print(e)
    niche = Counter(d.get("niche") for d in dests)
    print(f"行き先 {len(dests)} 件 / スポット {sum(len(d.get('spots', [])) for d in dests)} 件 / "
          f"ニッチ度分布 {dict(sorted(niche.items()))} / エラー {len(errors)} 件")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
