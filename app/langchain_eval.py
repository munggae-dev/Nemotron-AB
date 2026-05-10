"""LangChain ChatOllama 기반 단일 페르소나 평가 (태스크 워커용)."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.campaign_assets import image_ref_to_data_url

from script.marketing_validator import (
    Persona,
    _extract_json_object,
    build_eval_json_schema,
    build_prompt,
    campaign_has_images,
    confidence_from_margin,
    weighted_sum,
)


def _multimodal_message_content(
    persona: Persona,
    campaign: Dict[str, Any],
    metrics: Dict[str, float],
    max_reason_chars: int,
) -> List[Dict[str, Any]]:
    json_schema = build_eval_json_schema(metrics, max_reason_chars)
    metric_keys = ", ".join(metrics.keys())
    intro = (
        "당신은 마케팅 크리에이티브 A/B 심사 모델입니다.\n"
        "아래 페르소나 기준으로 안 A와 안 B를 비교합니다. "
        "각 안은 카피와(있는 경우) 바로 아래에 제시되는 이미지를 하나의 광고안으로 간주하세요.\n"
    )
    copy_a = str(campaign.get("copy_a", "") or "").strip() or "(없음)"
    copy_b = str(campaign.get("copy_b", "") or "").strip() or "(없음)"
    lines = [
        intro,
        f"- 평가 지표: {metric_keys}",
        "- 점수 범위: 각 지표 0~100 정수",
        "- 출력은 오직 JSON만 허용",
        "",
        f"[페르소나]\n{json.dumps(persona.raw, ensure_ascii=False)}",
        f"[캠페인 맥락]\n{json.dumps(campaign.get('context', {}), ensure_ascii=False)}",
        f"[카피 A]\n{copy_a}",
        f"[카피 B]\n{copy_b}",
    ]
    order: List[str] = []
    if isinstance(campaign.get("image_a"), dict) and str(campaign["image_a"].get("value", "")).strip():
        order.append("A")
    if isinstance(campaign.get("image_b"), dict) and str(campaign["image_b"].get("value", "")).strip():
        order.append("B")
    if order:
        joined = ", ".join(order)
        lines.append(f"이 메시지 하단 이미지는 순서대로 안 {joined}의 시각 크리에이티브입니다.")
    lines.append(f"[JSON 스키마]\n{json.dumps(json_schema, ensure_ascii=False)}")
    text = "\n".join(lines)
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    for key in ("image_a", "image_b"):
        ref = campaign.get(key)
        if isinstance(ref, dict) and str(ref.get("value", "")).strip():
            url = image_ref_to_data_url(ref)
            content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def evaluate_persona_ollama_langchain(
    persona: Persona,
    campaign: Dict[str, Any],
    metrics: Dict[str, float],
    max_reason_chars: int,
    ollama_model: str,
    ollama_base_url: str = "http://localhost:11434",
) -> Dict[str, Any]:
    from langchain_core.messages import HumanMessage
    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=ollama_model,
        temperature=0.1,
        base_url=ollama_base_url.rstrip("/"),
    )
    if campaign_has_images(campaign):
        parts = _multimodal_message_content(
            persona=persona,
            campaign=campaign,
            metrics=metrics,
            max_reason_chars=max_reason_chars,
        )
        resp = llm.invoke([HumanMessage(content=parts)])
    else:
        prompt = build_prompt(
            persona=persona,
            campaign=campaign,
            metrics=metrics,
            max_reason_chars=max_reason_chars,
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
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
    return {
        "winner": winner,
        "scores": scores,
        "reason": reason,
        "weighted_score": {"A": score_a, "B": score_b},
        "confidence": confidence_from_margin(score_a, score_b),
    }
