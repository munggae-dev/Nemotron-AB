"""V4: build_prompt 일반화 + evaluate_with_mock.

마케팅 전용 문구가 제거되고 단문 A/B 평가용으로 일반화됐는지 회귀를 막는다.
"""
from __future__ import annotations

from scripts.ab_validator import (
    DEFAULT_METRIC_WEIGHTS,
    Persona,
    build_prompt,
    evaluate_with_mock,
)


def _persona() -> Persona:
    return Persona(persona_id="p1", age=30, bucket="30s", raw={"age": 30, "occupation": "디자이너"})


def _campaign() -> dict:
    return {"id": "c1", "context": "신규 가입 안내 문구 A/B", "text_a": "오늘 가입", "text_b": "내일 가입"}


def test_build_prompt_uses_general_terms() -> None:
    prompt = build_prompt(_persona(), _campaign(), DEFAULT_METRIC_WEIGHTS, max_reason_chars=80)
    # 일반화된 표현이 등장해야 한다
    assert "단문(텍스트) A/B 평가 모델" in prompt
    assert "[텍스트 A]" in prompt and "[텍스트 B]" in prompt
    assert "신규 가입 안내 문구 A/B" in prompt
    # 마케팅 전용 어휘는 사라져야 한다
    assert "마케팅 카피" not in prompt
    assert "광고" not in prompt
    assert "카피" not in prompt


def test_evaluate_with_mock_produces_valid_scores() -> None:
    out = evaluate_with_mock(_persona(), _campaign(), DEFAULT_METRIC_WEIGHTS, seed=42)
    assert out["winner"] in ("A", "B")
    for arm in ("A", "B"):
        scores = out["scores"][arm]
        for metric in DEFAULT_METRIC_WEIGHTS:
            assert metric in scores
            assert 0 <= scores[metric] <= 100


def test_evaluate_with_mock_is_deterministic_for_same_seed() -> None:
    a = evaluate_with_mock(_persona(), _campaign(), DEFAULT_METRIC_WEIGHTS, seed=42)
    b = evaluate_with_mock(_persona(), _campaign(), DEFAULT_METRIC_WEIGHTS, seed=42)
    assert a == b
