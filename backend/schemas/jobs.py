"""Job·페르소나 필터 관련 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PersonaFilterIn(BaseModel):
    """Nemotron-Personas-Korea 벡터DB 메타 및 시·군·구 필터(빈 문자열은 미적용)."""

    sex: str = "all"
    age_min: int = Field(20, ge=19, le=59)
    age_max: int = Field(50, ge=19, le=59)
    province: str = ""
    district: str = ""
    marital_status: str = ""
    education_level: str = ""
    family_type: str = ""
    housing_type: str = ""
    military_status: str = ""
    occupation_contains: str = Field("", max_length=80)


class ImageRefIn(BaseModel):
    """업로드 선행 시 POST /jobs/assets 로 받은 staging 참조, 또는 공개 https URL."""

    type: str  # url | asset_ref
    value: str


class JobCreate(BaseModel):
    title: str = "신규 A/B 평가"
    text_a: str = Field("", max_length=2000)
    text_b: str = Field("", max_length=2000)
    image_a: ImageRefIn | None = None
    image_b: ImageRefIn | None = None
    context: str = Field("", max_length=4000)
    profile: str = "small"
    evaluator: str = "mock"
    llm_base_url: str = ""
    llm_model: str = ""
    response_format_json: bool = False
    prompt_profile: str = "full"
    """프롬프트 프로파일: 'full' (raw 페르소나) 또는 'compact' (핵심 필드만, 토큰 절감)."""
    max_persona_chars: int = Field(1500, ge=200, le=10000)
    """프롬프트에 들어가는 페르소나 JSON 문자열 길이 상한."""
    max_context_chars: int = Field(4000, ge=100, le=20000)
    """text_a + text_b + context 누적 길이 상한 (Pydantic max_length 외 통합 가드)."""
    max_personas: int = Field(24, ge=8, le=200)
    retrieval_k_per_bucket: int = Field(80, ge=20, le=500)
    eval_concurrency: int = Field(2, ge=1, le=8)
    seed: int = 42
    max_reason_chars: int = Field(80, ge=1, le=400)
    use_llm_task_queue: bool = True
    persona_filter: PersonaFilterIn


class JobCloneOptions(BaseModel):
    """원본 job 재실행 옵션. 모두 비워두면 원본 그대로 복제·재실행."""

    title: str | None = None
