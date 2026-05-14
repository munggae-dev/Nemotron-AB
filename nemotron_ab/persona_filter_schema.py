"""Nemotron-Personas-Korea 타깃 파일 기준 카테고리 후보(API 검증·/meta 라벨링용).

직업(occupation)은 문자열 다양성이 커 부분 문자열 검색(occupation_contains)으로 처리합니다."""

from collections.abc import Mapping

# target_personas_20_59.jsonl 전량 스트림 uniq (669,558건)
MARITAL_STATUS_OPTIONS: tuple[str, ...] = (
    "미혼",
    "배우자있음",
    "사별",
    "이혼",
)

EDUCATION_LEVEL_OPTIONS: tuple[str, ...] = (
    "2~3년제 전문대학",
    "4년제 대학교",
    "고등학교",
    "대학원",
    "무학",
    "중학교",
    "초등학교",
)

HOUSING_TYPE_OPTIONS: tuple[str, ...] = (
    "다세대주택",
    "단독주택",
    "비주거용 건물 내 주택",
    "아파트",
    "연립주택",
    "주택 이외의 거처",
)

MILITARY_STATUS_OPTIONS: tuple[str, ...] = (
    "비현역",
    "현역",
)

FAMILY_TYPE_OPTIONS: tuple[str, ...] = (
    "4세대이상",
    "가구주+기타친인척",
    "기타1세대",
    "기타2세대",
    "기타3세대",
    "배우자·미혼 형제자매와 거주",
    "배우자·부모와 거주",
    "배우자·손자녀와 거주",
    "배우자·자녀·부모와 거주",
    "배우자·자녀·아버지와 거주",
    "배우자·자녀·어머니와 거주",
    "배우자·자녀·형제자매와 거주",
    "배우자·자녀와 거주",
    "배우자·친인척과 거주",
    "배우자·편부모와 거주",
    "배우자·형제자매와 거주",
    "배우자와 거주",
    "부 또는 모와 거주",
    "부모·조모와 동거",
    "부모·조부모와 동거",
    "부모·조부와 동거",
    "부모·친인척과 동거",
    "부모·형제자매와 동거",
    "부모와 동거",
    "비친족 동거",
    "손자녀와 거주",
    "아버지와 동거",
    "어머니와 동거",
    "자녀·아버지와 거주",
    "자녀·어머니와 거주",
    "자녀와 거주 (배우자 별거)",
    "자녀와 거주 (한부모)",
    "조부 또는 조모와 동거",
    "조부모와 거주",
    "친인척과 거주",
    "형제 부부 가구에 동거",
    "형제자매와 동거 (가구주)",
    "혼자 거주",
    "혼자 거주 (배우자 별거)",
)

FILTER_ENUMS_FOR_META: Mapping[str, list[str]] = {
    "marital_status": list(MARITAL_STATUS_OPTIONS),
    "education_level": list(EDUCATION_LEVEL_OPTIONS),
    "family_type": list(FAMILY_TYPE_OPTIONS),
    "housing_type": list(HOUSING_TYPE_OPTIONS),
    "military_status": list(MILITARY_STATUS_OPTIONS),
}

FILTER_ENUM_LOOKUP: dict[str, frozenset] = {
    k: frozenset(v) for k, v in FILTER_ENUMS_FOR_META.items()
}

FIELD_LABEL_KO = {
    "marital_status": "혼인 상태",
    "education_level": "최종 학력",
    "family_type": "가구 종류",
    "housing_type": "주택 유형",
    "military_status": "병역 상태",
}


def retrieval_fanout_multiplier(persona_filter: Mapping[str, object]) -> int:
    """Chroma 결과 부족을 줄이기 위한 검색량 배수."""
    pf = persona_filter
    slots = ["marital_status", "education_level", "family_type", "housing_type", "military_status"]
    m = sum(1 for k in slots if str(pf.get(k, "") or "").strip())
    if str(pf.get("occupation_contains", "") or "").strip():
        m += 6
    return max(1, min(35, m * 4 + 1))
