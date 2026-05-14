"""V7-b: nemotron_ab.llm_provider.extract_usage 4 케이스.

LangChain 응답에서 토큰 사용량을 안전하게 뽑는지 검증한다.
"""
from __future__ import annotations

from tests.conftest import _FakeAIMsg


def test_extract_usage_from_usage_metadata() -> None:
    from nemotron_ab.llm_provider import extract_usage

    resp = _FakeAIMsg(
        content="{}",
        usage_metadata={"input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
    )
    assert extract_usage(resp) == {
        "prompt_tokens": 200,
        "completion_tokens": 80,
        "total_tokens": 280,
    }


def test_extract_usage_infers_total_from_sum() -> None:
    """total_tokens 가 누락된 경우 input + output 으로 계산해야 한다."""
    from nemotron_ab.llm_provider import extract_usage

    resp = _FakeAIMsg(
        content="{}",
        usage_metadata={"input_tokens": 11, "output_tokens": 22},
    )
    assert extract_usage(resp) == {
        "prompt_tokens": 11,
        "completion_tokens": 22,
        "total_tokens": 33,
    }


def test_extract_usage_falls_back_to_response_metadata() -> None:
    """usage_metadata 가 없으면 OpenAI 원시 응답 token_usage 를 봐야 한다."""
    from nemotron_ab.llm_provider import extract_usage

    resp = _FakeAIMsg(
        content="{}",
        usage_metadata=None,
        response_metadata={
            "token_usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200}
        },
    )
    assert extract_usage(resp) == {
        "prompt_tokens": 150,
        "completion_tokens": 50,
        "total_tokens": 200,
    }


def test_extract_usage_returns_zero_when_missing() -> None:
    from nemotron_ab.llm_provider import extract_usage

    resp = _FakeAIMsg(content="{}", usage_metadata=None, response_metadata={})
    assert extract_usage(resp) == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def test_llm_config_masks_api_key_in_repr() -> None:
    from nemotron_ab.llm_provider import LLMConfig

    cfg = LLMConfig(base_url="http://x/v1", model="m", api_key="sk-secret-123")
    text = repr(cfg)
    assert "sk-secret-123" not in text
    assert "***" in text


def test_resolve_llm_config_strips_trailing_slash_and_uses_env(monkeypatch) -> None:
    from nemotron_ab.llm_provider import resolve_llm_config

    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1/")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    cfg = resolve_llm_config()
    assert cfg.base_url == "https://api.openai.com/v1"  # trailing slash 제거
    assert cfg.model == "gpt-4o-mini"
    assert cfg.api_key == "sk-test"


def test_resolve_llm_config_explicit_args_override_env(monkeypatch) -> None:
    from nemotron_ab.llm_provider import resolve_llm_config

    monkeypatch.setenv("LLM_BASE_URL", "http://env/v1")
    cfg = resolve_llm_config(base_url="http://arg/v1", model="m", api_key="k")
    assert cfg.base_url == "http://arg/v1"
