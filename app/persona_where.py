"""페르소나 필터를 Chroma `$and` 조건 목록으로 변환합니다."""
from __future__ import annotations

from typing import Any, Dict, List

_NEMOTRON_META_KEYS = (
    "marital_status",
    "education_level",
    "family_type",
    "housing_type",
    "military_status",
)


def chroma_where_conditions(persona_filter: Dict[str, Any]) -> List[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = [
        {"age": {"$gte": int(persona_filter["age_min"])}},
        {"age": {"$lte": int(persona_filter["age_max"])}},
    ]
    sex = persona_filter.get("sex", "all")
    if sex != "all":
        clauses.append({"sex": sex})
    province = str(persona_filter.get("province", "") or "").strip()
    if province:
        clauses.append({"province": province})
    district = str(persona_filter.get("district", "") or "").strip()
    if district:
        clauses.append({"district": district})
    for key in _NEMOTRON_META_KEYS:
        val = str(persona_filter.get(key, "") or "").strip()
        if val:
            clauses.append({key: val})
    return clauses


def chroma_where_and(persona_filter: Dict[str, Any]) -> Dict[str, Any]:
    return {"$and": chroma_where_conditions(persona_filter)}
