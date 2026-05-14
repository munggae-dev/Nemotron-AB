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


_PROVINCE_ALIAS = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원특별자치도": "강원",
    "강원도": "강원",
    "충청북도": "충청북",
    "충청남도": "충청남",
    "전북특별자치도": "전북",
    "전라북도": "전북",
    "전라남도": "전라남",
    "경상북도": "경상북",
    "경상남도": "경상남",
    "제주특별자치도": "제주",
}


def normalize_province(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    return _PROVINCE_ALIAS.get(v, v)


def _normalize_district(province_norm: str, district_raw: str) -> str:
    d = str(district_raw or "").strip()
    if not d:
        return ""
    # persona_db에는 "서울-강남구", "경기-성남시 분당구" 형태가 많음
    if "-" in d or not province_norm:
        return d
    return f"{province_norm}-{d}"


def district_exact_token(persona_filter: Dict[str, Any]) -> str:
    """district 완전일치 키를 돌려준다(입력이 이미 full token일 때만)."""
    district_raw = str(persona_filter.get("district", "") or "").strip()
    if not district_raw:
        return ""
    # 사용자가 full token(예: 경기-성남시 분당구)을 직접 준 경우만 완전일치 where 사용
    if "-" in district_raw:
        return district_raw
    return ""


def district_prefix_keyword(persona_filter: Dict[str, Any]) -> str:
    """district 부분일치 키를 만든다(예: '경기도' + '성남시' -> '경기-성남시')."""
    province = normalize_province(str(persona_filter.get("province", "") or ""))
    district_raw = str(persona_filter.get("district", "") or "").strip()
    if not district_raw or not province:
        return ""
    # 사용자가 full token을 넣은 경우 그대로 사용
    if "-" in district_raw:
        return district_raw
    return f"{province}-{district_raw}"


def chroma_where_conditions(persona_filter: Dict[str, Any]) -> List[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = [
        {"age": {"$gte": int(persona_filter["age_min"])}},
        {"age": {"$lte": int(persona_filter["age_max"])}},
    ]
    sex = persona_filter.get("sex", "all")
    if sex != "all":
        clauses.append({"sex": sex})
    province = normalize_province(str(persona_filter.get("province", "") or ""))
    if province:
        clauses.append({"province": province})
    # district는 full token일 때만 where 완전일치, 그 외(예: 성남시)는 후처리 부분일치.
    district = district_exact_token(persona_filter)
    if district:
        clauses.append({"district": district})
    for key in _NEMOTRON_META_KEYS:
        val = str(persona_filter.get(key, "") or "").strip()
        if val:
            clauses.append({key: val})
    return clauses


def chroma_where_and(persona_filter: Dict[str, Any]) -> Dict[str, Any]:
    return {"$and": chroma_where_conditions(persona_filter)}
