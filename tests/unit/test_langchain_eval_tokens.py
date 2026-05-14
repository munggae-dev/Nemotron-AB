"""evaluate_persona_langchain 토큰 흐름 (fake ChatOpenAI 주입).

ChatOpenAI 를 외부 호출 없이 가짜 응답으로 교체해, 결과·토큰이 함께 반환되는지
end-to-end 흐름을 검증한다.
"""
from __future__ import annotations


def _persona():
    from scripts.ab_validator import Persona

    return Persona(persona_id="p1", age=30, bucket="30s", raw={"age": 30, "occupation": "디자이너"})


def _campaign():
    return {
        "id": "c1",
        "context": "신규 가입 안내",
        "text_a": "오늘 가입",
        "text_b": "내일 가입",
    }


def _cfg():
    from nemotron_ab.llm_provider import LLMConfig

    return LLMConfig(base_url="http://fake/v1", model="fake-model", api_key="EMPTY")


def test_evaluate_returns_result_and_usage(fake_chat_openai_factory) -> None:
    fake_chat_openai_factory(
        usage_metadata={"input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
    )
    # fake module 설치 후에 재import (conftest 가 sys.modules 청소함)
    from nemotron_ab.langchain_eval import evaluate_persona_langchain
    from scripts.ab_validator import DEFAULT_METRIC_WEIGHTS

    result, usage = evaluate_persona_langchain(
        _persona(),
        _campaign(),
        DEFAULT_METRIC_WEIGHTS,
        max_reason_chars=80,
        llm_config=_cfg(),
    )
    assert result["winner"] == "A"
    assert "weighted_score" in result and "confidence" in result
    for metric in DEFAULT_METRIC_WEIGHTS:
        assert metric in result["scores"]["A"]
        assert 0 <= result["scores"]["A"][metric] <= 100
    assert usage == {
        "prompt_tokens": 200,
        "completion_tokens": 80,
        "total_tokens": 280,
    }


def test_evaluate_works_with_response_metadata_fallback(fake_chat_openai_factory) -> None:
    fake_chat_openai_factory(
        usage_metadata=None,
        response_metadata={
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
        },
    )
    from nemotron_ab.langchain_eval import evaluate_persona_langchain
    from scripts.ab_validator import DEFAULT_METRIC_WEIGHTS

    _result, usage = evaluate_persona_langchain(
        _persona(),
        _campaign(),
        DEFAULT_METRIC_WEIGHTS,
        max_reason_chars=80,
        llm_config=_cfg(),
    )
    assert usage == {
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
    }


def test_evaluate_handles_missing_usage_gracefully(fake_chat_openai_factory) -> None:
    fake_chat_openai_factory(usage_metadata=None, response_metadata={})
    from nemotron_ab.langchain_eval import evaluate_persona_langchain
    from scripts.ab_validator import DEFAULT_METRIC_WEIGHTS

    _result, usage = evaluate_persona_langchain(
        _persona(),
        _campaign(),
        DEFAULT_METRIC_WEIGHTS,
        max_reason_chars=80,
        llm_config=_cfg(),
    )
    assert usage == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def test_evaluate_accepts_max_persona_chars(fake_chat_openai_factory) -> None:
    """evaluate_persona_langchain 이 max_persona_chars 인자를 받아 정상 동작한다."""
    fake_chat_openai_factory(usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})

    from nemotron_ab.langchain_eval import evaluate_persona_langchain
    from scripts.ab_validator import DEFAULT_METRIC_WEIGHTS, Persona

    persona = Persona(
        persona_id="p1",
        age=30,
        bucket="30s",
        raw={
            "age": 30,
            "occupation": "디자이너",
            "note": "한국어로 길게 쓰인 페르소나 노트 입니다. " * 30,
        },
    )
    result, usage = evaluate_persona_langchain(
        persona,
        _campaign(),
        DEFAULT_METRIC_WEIGHTS,
        max_reason_chars=80,
        llm_config=_cfg(),
        max_persona_chars=200,
    )
    assert result["winner"] in ("A", "B")
    assert usage["total_tokens"] == 15
