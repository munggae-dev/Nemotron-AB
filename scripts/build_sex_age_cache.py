"""성별·나이 사전 집계 캐시 생성 스크립트."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nemotron_ab.persona_population_cache import CACHE_PATH, build_sex_age_cache


def main() -> None:
    payload = build_sex_age_cache()
    print(f"saved: {CACHE_PATH}")
    print(f"total_indexed: {payload.get('total_indexed', 0)}")


if __name__ == "__main__":
    main()

