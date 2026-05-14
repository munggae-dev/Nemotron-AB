"""OpenAI-호환 LLM 제공자 어댑터.

이 모듈은 평가용 LLM 호출을 OpenAI-호환 엔드포인트 하나로 통일합니다.
Ollama(`/v1`), OpenAI, Azure OpenAI, OpenRouter, Together, vLLM, llama.cpp, NVIDIA NIM 등이
같은 인터페이스로 동작합니다.

설정 우선순위:
1. 함수 인자(`base_url`, `model`, `api_key`)
2. 환경변수 `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`
3. 기본값(`http://localhost:11434/v1`, "gemma3:4b-it-qat", "EMPTY")

API 키는 보안상 **환경변수만** 수용합니다. 함수 인자로 받는 경우는
프로그램 내부 호출(서브프로세스 등) 한정입니다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "gemma3:4b-it-qat"
DEFAULT_API_KEY = "EMPTY"

ENV_BASE_URL = "LLM_BASE_URL"
ENV_MODEL = "LLM_MODEL"
ENV_API_KEY = "LLM_API_KEY"


@dataclass(frozen=True)
class LLMConfig:
    """평가 호출에 사용할 LLM 설정.

    `api_key`는 직렬화/로그에 노출하면 안 됩니다. 객체는 frozen이며
    `__repr__`에서 키는 마스킹됩니다.
    """

    base_url: str
    model: str
    api_key: str
    temperature: float = 0.1
    request_timeout_sec: float | None = None

    def __repr__(self) -> str:
        masked = "***" if self.api_key else "(empty)"
        return (
            f"LLMConfig(base_url={self.base_url!r}, model={self.model!r}, "
            f"api_key={masked}, temperature={self.temperature})"
        )

    def to_safe_dict(self) -> dict[str, Any]:
        """로그/응답용 안전 직렬화 (api_key 제외)."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "request_timeout_sec": self.request_timeout_sec,
        }


def resolve_llm_config(
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.1,
    request_timeout_sec: float | None = None,
) -> LLMConfig:
    """인자 > 환경변수 > 기본값 순으로 설정을 결정합니다."""
    resolved_base = (base_url or os.environ.get(ENV_BASE_URL, "") or DEFAULT_BASE_URL).rstrip("/")
    resolved_model = model or os.environ.get(ENV_MODEL, "") or DEFAULT_MODEL
    resolved_key = api_key or os.environ.get(ENV_API_KEY, "") or DEFAULT_API_KEY
    return LLMConfig(
        base_url=resolved_base,
        model=resolved_model,
        api_key=resolved_key,
        temperature=temperature,
        request_timeout_sec=request_timeout_sec,
    )


def make_chat_llm(config: LLMConfig, *, response_format_json: bool = False) -> Any:
    """OpenAI-호환 ChatOpenAI 인스턴스를 생성합니다.

    `response_format_json=True` 인 경우 응답을 JSON 객체로 강제합니다.
    (OpenAI 계열만 지원. Ollama 등은 무시될 수 있습니다.)
    """
    from langchain_openai import ChatOpenAI

    extra: dict[str, Any] = {}
    if response_format_json:
        extra["model_kwargs"] = {"response_format": {"type": "json_object"}}
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        "base_url": config.base_url,
        "api_key": config.api_key,
        **extra,
    }
    if config.request_timeout_sec is not None:
        kwargs["timeout"] = config.request_timeout_sec
    return ChatOpenAI(**kwargs)


def extract_usage(response: Any) -> dict[str, int]:
    """LangChain AIMessage 응답에서 토큰 사용량을 추출합니다.

    표준 필드 `usage_metadata` (input_tokens/output_tokens/total_tokens)를
    우선하고, 없으면 OpenAI 원시 응답의 `response_metadata.token_usage` 를
    조회합니다. 값이 없으면 0으로 둡니다.
    """
    prompt = 0
    completion = 0
    total = 0

    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        prompt = int(usage.get("input_tokens", 0) or 0)
        completion = int(usage.get("output_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or (prompt + completion))

    if prompt == 0 and completion == 0:
        rm = getattr(response, "response_metadata", None)
        if isinstance(rm, dict):
            tu = rm.get("token_usage") or rm.get("usage") or {}
            if isinstance(tu, dict):
                prompt = int(tu.get("prompt_tokens", tu.get("input_tokens", 0)) or 0)
                completion = int(tu.get("completion_tokens", tu.get("output_tokens", 0)) or 0)
                total = int(tu.get("total_tokens", 0) or (prompt + completion))

    if total == 0:
        total = prompt + completion

    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}
