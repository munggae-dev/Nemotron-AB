"""JobCreate → 워커/DB용 payload dict 변환."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.schemas.jobs import JobCreate
from backend.services.job_validation import optional_image_payload


def payload_from_create(body: JobCreate) -> dict[str, Any]:
    img_a = optional_image_payload(body.image_a)
    img_b = optional_image_payload(body.image_b)
    text_a = body.text_a.strip()
    text_b = body.text_b.strip()
    context = body.context.strip()
    total_len = len(text_a) + len(text_b) + len(context)
    if total_len > body.max_context_chars:
        raise HTTPException(
            400,
            f"text_a + text_b + context 누적 길이({total_len}) 가 "
            f"max_context_chars({body.max_context_chars}) 를 초과합니다.",
        )
    from nemotron_ab.prompt_profile import VALID_PROFILES

    profile_name = str(body.prompt_profile or "full").strip().lower()
    if profile_name not in VALID_PROFILES:
        raise HTTPException(
            400,
            f"prompt_profile 은 {VALID_PROFILES} 중 하나여야 합니다 (입력: {body.prompt_profile!r}).",
        )
    return {
        "title": body.title,
        "text_a": text_a,
        "text_b": text_b,
        "image_a": img_a,
        "image_b": img_b,
        "context": context,
        "profile": body.profile,
        "evaluator": body.evaluator,
        "llm_base_url": body.llm_base_url.strip().rstrip("/"),
        "llm_model": body.llm_model.strip(),
        "response_format_json": bool(body.response_format_json),
        "prompt_profile": profile_name,
        "max_persona_chars": int(body.max_persona_chars),
        "max_context_chars": int(body.max_context_chars),
        "max_personas": body.max_personas,
        "retrieval_k_per_bucket": body.retrieval_k_per_bucket,
        "eval_concurrency": body.eval_concurrency,
        "seed": body.seed,
        "max_reason_chars": body.max_reason_chars,
        "persona_filter": body.persona_filter.model_dump(),
    }
