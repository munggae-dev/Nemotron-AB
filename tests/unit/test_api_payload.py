"""V3: backend.JobCreate → _payload_from_create 변환.

새 LLM 일반화 스키마(`text_a/b`, `context`, `llm_base_url`/`llm_model`,
`response_format_json`) 와 레거시 `ollama_*` 제거를 검증한다.
"""
from __future__ import annotations

import pytest


def _make_filter():
    from backend.main import PersonaFilterIn

    return PersonaFilterIn(
        sex="all",
        age_min=20,
        age_max=50,
        province="",
        district="",
    )


def test_payload_uses_new_text_and_context_fields(isolated_sqlite) -> None:
    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="안녕",
        text_b="반가워",
        context="가입 알림 카피 A/B (30대 여성)",
        llm_base_url="https://api.openai.com/v1/",
        llm_model="gpt-4o-mini",
        response_format_json=True,
        persona_filter=_make_filter(),
    )
    payload = _payload_from_create(body)
    assert payload["text_a"] == "안녕"
    assert payload["text_b"] == "반가워"
    assert payload["context"] == "가입 알림 카피 A/B (30대 여성)"
    # base_url 의 trailing slash 는 제거된다
    assert payload["llm_base_url"] == "https://api.openai.com/v1"
    assert payload["llm_model"] == "gpt-4o-mini"
    assert payload["response_format_json"] is True


def test_payload_does_not_leak_legacy_keys(isolated_sqlite) -> None:
    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="a",
        text_b="b",
        context="c",
        llm_base_url="http://localhost:11434/v1",
        llm_model="gemma3:4b-it-qat",
        persona_filter=_make_filter(),
    )
    payload = _payload_from_create(body)
    for legacy in ("copy_a", "copy_b", "product", "category", "tone", "goal", "description",
                   "ollama_model", "ollama_base_url"):
        assert legacy not in payload, f"legacy key leaked: {legacy}"


def test_payload_includes_filter_dict(isolated_sqlite) -> None:
    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="a",
        text_b="b",
        context="c",
        persona_filter=_make_filter(),
    )
    payload = _payload_from_create(body)
    assert isinstance(payload["persona_filter"], dict)
    assert payload["persona_filter"]["sex"] == "all"
    assert payload["persona_filter"]["age_min"] == 20
    assert payload["persona_filter"]["age_max"] == 50


def test_payload_default_prompt_profile_and_caps(isolated_sqlite) -> None:
    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="a",
        text_b="b",
        context="c",
        persona_filter=_make_filter(),
    )
    payload = _payload_from_create(body)
    assert payload["prompt_profile"] == "full"
    assert payload["max_persona_chars"] == 1500
    assert payload["max_context_chars"] == 4000


def test_payload_propagates_prompt_profile(isolated_sqlite) -> None:
    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="a",
        text_b="b",
        context="c",
        prompt_profile="compact",
        max_persona_chars=900,
        max_context_chars=2000,
        persona_filter=_make_filter(),
    )
    payload = _payload_from_create(body)
    assert payload["prompt_profile"] == "compact"
    assert payload["max_persona_chars"] == 900
    assert payload["max_context_chars"] == 2000


def test_payload_rejects_invalid_prompt_profile(isolated_sqlite) -> None:
    from fastapi import HTTPException

    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="a",
        text_b="b",
        context="c",
        prompt_profile="bogus",
        persona_filter=_make_filter(),
    )
    with pytest.raises(HTTPException) as exc:
        _payload_from_create(body)
    assert exc.value.status_code == 400
    assert "prompt_profile" in str(exc.value.detail)


def test_payload_rejects_overlong_context_sum(isolated_sqlite) -> None:
    from fastapi import HTTPException

    from backend.main import JobCreate, _payload_from_create

    body = JobCreate(
        title="t",
        text_a="A" * 600,
        text_b="B" * 600,
        context="C" * 800,
        max_context_chars=1500,  # 누적 2000 > 1500 → 거절
        persona_filter=_make_filter(),
    )
    with pytest.raises(HTTPException) as exc:
        _payload_from_create(body)
    assert exc.value.status_code == 400
    assert "max_context_chars" in str(exc.value.detail)


def test_jobcreate_rejects_overlong_individual_text() -> None:
    """Pydantic 단계에서 text_a/b max_length 가 적용된다."""
    from pydantic import ValidationError

    from backend.main import JobCreate

    with pytest.raises(ValidationError):
        JobCreate(
            text_a="x" * 3000,  # 2000 초과
            text_b="b",
            context="c",
            persona_filter=_make_filter(),
        )
