"""LangChain 기반 단일 페르소나 평가 (태스크 워커용).

호출은 OpenAI-호환 엔드포인트(`ChatOpenAI(base_url=...)`)로 통일됩니다.
Ollama 도 `/v1` 경로(예: `http://localhost:11434/v1`)로 같은 인터페이스에서 동작합니다.
"""
from __future__ import annotations

import json
from typing import Any

from nemotron_ab.campaign_assets import image_ref_to_data_url
from nemotron_ab.llm_provider import LLMConfig, extract_usage, make_chat_llm, resolve_llm_config
from nemotron_ab.prompt_profile import truncate_persona_view
from scripts.ab_validator import (
    Persona,
    _extract_json_object,
    build_eval_json_schema,
    build_prompt,
    campaign_has_images,
    confidence_from_margin,
    persona_view_for_prompt,
    weighted_sum,
)


def _multimodal_message_content(
    persona: Persona,
    campaign: dict[str, Any],
    metrics: dict[str, float],
    max_reason_chars: int,
    image_max_dim: int | None = None,
    persona_view: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    json_schema = build_eval_json_schema(metrics, max_reason_chars)
    metric_keys = ", ".join(metrics.keys())
    intro = (
        "당신은 단문·이미지 A/B 평가 모델입니다.\n"
        "아래 페르소나 기준으로 안 A 와 안 B 를 비교합니다. "
        "각 안은 텍스트와(있는 경우) 바로 아래에 제시되는 이미지를 하나의 안으로 간주하세요.\n"
    )
    text_a = str(campaign.get("text_a", "") or "").strip() or "(없음)"
    text_b = str(campaign.get("text_b", "") or "").strip() or "(없음)"
    context = str(campaign.get("context", "") or "").strip() or "(맥락 없음)"
    persona_payload = persona_view if persona_view is not None else persona.raw
    lines = [
        intro,
        f"- 평가 지표: {metric_keys}",
        "- 점수 범위: 각 지표 0~100 정수",
        "- 출력은 오직 JSON만 허용",
        "",
        f"[페르소나]\n{json.dumps(persona_payload, ensure_ascii=False)}",
        f"[맥락]\n{context}",
        f"[텍스트 A]\n{text_a}",
        f"[텍스트 B]\n{text_b}",
    ]
    order: list[str] = []
    if isinstance(campaign.get("image_a"), dict) and str(campaign["image_a"].get("value", "")).strip():
        order.append("A")
    if isinstance(campaign.get("image_b"), dict) and str(campaign["image_b"].get("value", "")).strip():
        order.append("B")
    if order:
        joined = ", ".join(order)
        lines.append(f"이 메시지 하단 이미지는 순서대로 안 {joined}의 시각 자료입니다.")
    lines.append(f"[JSON 스키마]\n{json.dumps(json_schema, ensure_ascii=False)}")
    text = "\n".join(lines)
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for key in ("image_a", "image_b"):
        ref = campaign.get(key)
        if isinstance(ref, dict) and str(ref.get("value", "")).strip():
            url = image_ref_to_data_url(ref, max_dim=image_max_dim)
            content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def evaluate_persona_langchain(
    persona: Persona,
    campaign: dict[str, Any],
    metrics: dict[str, float],
    max_reason_chars: int,
    *,
    llm_config: LLMConfig | None = None,
    image_max_dim: int | None = None,
    persona_fields: list[str] | None = None,
    persona_drop_fields: list[str] | None = None,
    response_format_json: bool = False,
    max_persona_chars: int | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """페르소나 1건에 대한 A/B 평가 호출.

    Returns:
        (parsed_result_dict, token_usage_dict)
    """
    from langchain_core.messages import HumanMessage

    cfg = llm_config or resolve_llm_config()
    llm = make_chat_llm(cfg, response_format_json=response_format_json)

    persona_view = persona_view_for_prompt(
        persona,
        fields=persona_fields,
        drop_keys=persona_drop_fields,
    )
    if max_persona_chars is not None and max_persona_chars > 0 and isinstance(persona_view, dict):
        persona_view = truncate_persona_view(persona_view, max_chars=max_persona_chars)
    if campaign_has_images(campaign):
        parts = _multimodal_message_content(
            persona=persona,
            campaign=campaign,
            metrics=metrics,
            max_reason_chars=max_reason_chars,
            image_max_dim=image_max_dim,
            persona_view=persona_view,
        )
        resp = llm.invoke([HumanMessage(content=parts)])
    else:
        prompt = build_prompt(
            persona=persona,
            campaign=campaign,
            metrics=metrics,
            max_reason_chars=max_reason_chars,
            persona_view=persona_view,
        )
        resp = llm.invoke([HumanMessage(content=prompt)])

    usage = extract_usage(resp)
    raw = (resp.content or "").strip()
    parsed = _extract_json_object(raw)

    winner = parsed.get("winner")
    scores = parsed.get("scores", {})
    reason = str(parsed.get("reason", "")).strip()
    if winner not in ("A", "B"):
        raise ValueError(f"winner 값이 유효하지 않음: {winner}")
    if len(reason) > max_reason_chars:
        reason = reason[:max_reason_chars]
    for arm in ("A", "B"):
        if arm not in scores:
            raise ValueError(f"scores.{arm} 누락")
        for metric in metrics.keys():
            if metric not in scores[arm]:
                raise ValueError(f"scores.{arm}.{metric} 누락")
            scores[arm][metric] = int(scores[arm][metric])
            scores[arm][metric] = max(0, min(100, scores[arm][metric]))

    score_a = weighted_sum(scores["A"], metrics)
    score_b = weighted_sum(scores["B"], metrics)
    result = {
        "winner": winner,
        "scores": scores,
        "reason": reason,
        "weighted_score": {"A": score_a, "B": score_b},
        "confidence": confidence_from_margin(score_a, score_b),
    }
    return result, usage
