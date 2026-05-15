from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.deps import get_conn
from backend.schemas.jobs import PersonaFilterIn
from backend.services.job_validation import validate_nemotron_persona_filter_enums
from backend.services.population_estimate import estimate_population_size
from nemotron_ab import db
from nemotron_ab.persona_filter_schema import (
    FIELD_LABEL_KO,
    FILTER_ENUM_LOOKUP,
    FILTER_ENUMS_FOR_META,
)
from nemotron_ab.persona_population_cache import load_cache, sum_count_from_cache
from nemotron_ab.regions import KOREA_REGIONS

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/regions")
def meta_regions() -> dict[str, list[str]]:
    return KOREA_REGIONS


@router.get("/persona-filters")
def meta_persona_filters() -> dict[str, Any]:
    """Nemotron-Personas-Korea 기반 벡터DB 필터 선택지(폼 채우기용)."""
    enum_fields = []
    for key, opt_list in FILTER_ENUMS_FOR_META.items():
        enum_fields.append(
            {
                "key": key,
                "label": FIELD_LABEL_KO.get(key, key),
                "options": [{"value": o, "label": o} for o in opt_list],
            }
        )
    return {
        "dataset": "nvidia/Nemotron-Personas-Korea",
        "age_range_note": "이 앱 데이터 파이프는 만 19~59 레코드를 사용합니다.",
        "enum_fields": enum_fields,
        "occupation_contains": {"max_chars": 80},
        "vectordb_hint": (
            "혼인·학력 등 메타는 scripts/build_vectordb.py 재생성 후 persona_db에 반영됩니다. "
            "이전 DB는 해당 필터 사용 시 결과가 비거나 무시될 수 있습니다."
        ),
    }


@router.post("/persona-population-estimate")
async def meta_persona_population_estimate(body: PersonaFilterIn) -> dict[str, Any]:
    if body.age_min > body.age_max:
        raise HTTPException(400, "age_min must be <= age_max")
    filter_payload = body.model_dump()
    validate_nemotron_persona_filter_enums(filter_payload)

    sex_age_only = (
        not str(filter_payload.get("province", "") or "").strip()
        and not str(filter_payload.get("district", "") or "").strip()
        and not str(filter_payload.get("occupation_contains", "") or "").strip()
        and all(not str(filter_payload.get(k, "") or "").strip() for k in FILTER_ENUM_LOOKUP.keys())
    )
    if sex_age_only:
        try:
            cache = await asyncio.to_thread(load_cache)
            if cache is not None:
                exact_count = sum_count_from_cache(
                    cache,
                    str(filter_payload.get("sex", "all")),
                    int(filter_payload.get("age_min", 19)),
                    int(filter_payload.get("age_max", 59)),
                )
                return {
                    "count": int(exact_count),
                    "note": "성별·나이 사전 집계 캐시 기준 정확값",
                    "capped": False,
                    "scanned": int(cache.get("total_indexed", 0) or 0),
                }
        except Exception:
            pass

    try:
        summary = await asyncio.to_thread(estimate_population_size, filter_payload)
    except Exception as e:
        raise HTTPException(500, f"모수 추정 실패: {e}") from e
    note = "현재 persona_db 기준 필터 매칭 레코드 수"
    if summary.get("capped"):
        note = "빠른 추정치(일부 스캔)입니다. 범위를 더 좁히면 정확도가 올라갑니다."
    return {
        "count": int(summary.get("count", 0)),
        "note": note,
        "capped": bool(summary.get("capped", False)),
        "scanned": int(summary.get("scanned", 0)),
    }


@router.get("/queue-stats")
def meta_queue_stats() -> dict[str, int | dict[str, int]]:
    """작업 상태별 건수(대시보드 KPI용)."""
    with get_conn() as conn:
        by_status = db.queue_status_counts(conn)
        total = sum(by_status.values())
        return {"total": total, "by_status": by_status}
