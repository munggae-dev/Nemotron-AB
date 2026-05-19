"""LLM usage 집계(평가 + 종합 분석) 단위 테스트."""
from __future__ import annotations

from nemotron_ab.llm_usage import build_job_llm_usage


def test_build_job_llm_usage_eval_only() -> None:
    usage = build_job_llm_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "llm_call_count": 8,
            "task_count": 8,
        }
    )
    assert usage["llm_call_count"] == 8
    assert usage["eval_call_count"] == 8
    assert usage["synthesis_call_count"] == 0
    assert usage["total_tokens"] == 140


def test_build_job_llm_usage_includes_synthesis() -> None:
    usage = build_job_llm_usage(
        {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200, "llm_call_count": 10},
        synthesis_tokens={"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
        synthesis_call_count=1,
    )
    assert usage["llm_call_count"] == 11
    assert usage["eval_call_count"] == 10
    assert usage["synthesis_call_count"] == 1
    assert usage["total_tokens"] == 1800
    assert usage["eval_total_tokens"] == 1200
    assert usage["synthesis_total_tokens"] == 600
