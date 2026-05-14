"""성별·나이 모수 사전 집계 캐시.

대용량 원본 페르소나 JSONL(예: target_personas_20_59.jsonl)을 한 번 스트리밍해
(sex, age) 카운트를 파일로 저장하고 재사용한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_JSONL = ROOT / "target_personas_20_59.jsonl"
CACHE_PATH = ROOT / "outputs" / "persona_sex_age_cache.json"


def _normalize_sex(value: Any) -> str:
    s = str(value or "").strip()
    if s in ("남", "남성"):
        return "남자"
    if s in ("여", "여성"):
        return "여자"
    if s in ("남자", "여자"):
        return s
    return "기타"


def _normalize_age(value: Any) -> int | None:
    try:
        age = int(value)
    except Exception:
        return None
    if age < 0 or age > 120:
        return None
    return age


def build_sex_age_cache(source_jsonl: Path = DEFAULT_SOURCE_JSONL) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {"all": {}, "남자": {}, "여자": {}, "기타": {}}
    total = 0
    with source_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                row = json.loads(s)
            except Exception:
                continue
            sex = _normalize_sex(row.get("sex"))
            age = _normalize_age(row.get("age"))
            if age is None:
                continue
            key = str(age)
            counts["all"][key] = counts["all"].get(key, 0) + 1
            counts[sex][key] = counts[sex].get(key, 0) + 1
            total += 1

    payload = {
        "version": 1,
        "source": str(source_jsonl),
        "total_indexed": total,
        "counts": counts,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def load_cache() -> dict[str, Any] | None:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def sum_count_from_cache(cache_payload: dict[str, Any], sex: str, age_min: int, age_max: int) -> int:
    sex_key = str(sex or "all").strip()
    if sex_key not in ("all", "남자", "여자"):
        sex_key = "all"
    bucket = (cache_payload.get("counts") or {}).get(sex_key) or {}
    total = 0
    for age in range(int(age_min), int(age_max) + 1):
        total += int(bucket.get(str(age), 0) or 0)
    return total

