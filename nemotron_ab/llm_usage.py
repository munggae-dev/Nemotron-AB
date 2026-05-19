"""작업 단위 LLM 토큰·호출 횟수 집계(페르소나 평가 + 종합 분석)."""
from __future__ import annotations

from typing import Any


def _int_tokens(d: dict[str, Any] | None, key: str) -> int:
    if not isinstance(d, dict):
        return 0
    return int(d.get(key, 0) or 0)


def build_job_llm_usage(
    eval_totals: dict[str, Any],
    *,
    synthesis_tokens: dict[str, Any] | None = None,
    synthesis_call_count: int = 0,
) -> dict[str, int]:
    """페르소나 평가 집계와 종합 분석 usage를 합친 보고서용 usage 블록."""
    eval_prompt = _int_tokens(eval_totals, "prompt_tokens")
    eval_completion = _int_tokens(eval_totals, "completion_tokens")
    eval_total = _int_tokens(eval_totals, "total_tokens")
    if eval_total == 0 and (eval_prompt or eval_completion):
        eval_total = eval_prompt + eval_completion

    syn = synthesis_tokens if isinstance(synthesis_tokens, dict) else {}
    syn_prompt = _int_tokens(syn, "prompt_tokens")
    syn_completion = _int_tokens(syn, "completion_tokens")
    syn_total = _int_tokens(syn, "total_tokens")
    if syn_total == 0 and (syn_prompt or syn_completion):
        syn_total = syn_prompt + syn_completion

    eval_calls = int(eval_totals.get("llm_call_count", eval_totals.get("task_count", 0)) or 0)
    syn_calls = max(0, int(synthesis_call_count))

    return {
        "prompt_tokens": eval_prompt + syn_prompt,
        "completion_tokens": eval_completion + syn_completion,
        "total_tokens": eval_total + syn_total,
        "eval_prompt_tokens": eval_prompt,
        "eval_completion_tokens": eval_completion,
        "eval_total_tokens": eval_total,
        "synthesis_prompt_tokens": syn_prompt,
        "synthesis_completion_tokens": syn_completion,
        "synthesis_total_tokens": syn_total,
        "llm_call_count": eval_calls + syn_calls,
        "eval_call_count": eval_calls,
        "synthesis_call_count": syn_calls,
        "task_count": eval_calls,
    }
