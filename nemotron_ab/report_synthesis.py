"""완료 리포트에 대한 LLM 종합 분석(1회 호출)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nemotron_ab import db
from nemotron_ab.campaign_assets import image_ref_to_data_url, payload_has_any_image
from nemotron_ab.llm_provider import LLMConfig, extract_usage, make_chat_llm, resolve_llm_config
from nemotron_ab.llm_usage import build_job_llm_usage

def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 응답에서 JSON 객체를 찾지 못했습니다.")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM 응답 JSON이 객체가 아닙니다.")
    return parsed


ENV_SYNTHESIS_BASE_URL = "LLM_SYNTHESIS_BASE_URL"
ENV_SYNTHESIS_MODEL = "LLM_SYNTHESIS_MODEL"
ENV_SYNTHESIS_TIMEOUT_SEC = "LLM_SYNTHESIS_TIMEOUT_SEC"
ENV_SYNTHESIS_MAX_EVAL_JSON_CHARS = "LLM_SYNTHESIS_MAX_EVAL_JSON_CHARS"

DEFAULT_SYNTHESIS_TIMEOUT_SEC = 120.0
DEFAULT_SYNTHESIS_MAX_EVAL_JSON_CHARS = 120_000

SYNTHESIS_JSON_SCHEMA_HINT = {
    "headline": "한 줄 결론 (최종 추천 Variant 포함)",
    "executive_summary": "2~4문단 종합 해석",
    "segment_notes": "연령대·조건부 추천 해석",
    "action_items": ["실행 제안 1", "실행 제안 2"],
    "limitations": "시뮬레이션·표본 한계",
    "full_markdown": "위 내용을 묶은 마크다운(선택)",
}


def _strip_opt(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _pick_url_or_model(*candidates: Any) -> str | None:
    for c in candidates:
        picked = _strip_opt(c)
        if picked:
            return picked
    return None


def resolve_synthesis_llm_config(
    *,
    body_base_url: str | None = None,
    body_model: str | None = None,
    job_payload: dict[str, Any] | None = None,
) -> LLMConfig:
    """종합 분석 LLM 설정: 요청 body > 작업 payload > synthesis env > 전역 env > 기본값."""
    payload = job_payload or {}
    env_syn_base = os.environ.get(ENV_SYNTHESIS_BASE_URL, "")
    env_syn_model = os.environ.get(ENV_SYNTHESIS_MODEL, "")
    base_url = _pick_url_or_model(
        body_base_url,
        payload.get("llm_base_url"),
        payload.get("ollama_url"),  # legacy
        env_syn_base,
    )
    model = _pick_url_or_model(
        body_model,
        payload.get("llm_model"),
        payload.get("ollama_model"),
        env_syn_model,
    )
    timeout_raw = os.environ.get(ENV_SYNTHESIS_TIMEOUT_SEC, "").strip()
    try:
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_SYNTHESIS_TIMEOUT_SEC
    except ValueError:
        timeout = DEFAULT_SYNTHESIS_TIMEOUT_SEC
    return resolve_llm_config(
        base_url=base_url,
        model=model,
        temperature=0.2,
        request_timeout_sec=timeout,
    )


def load_job_partial_eval_rows(job_id: int, *, partial_jsonl_path: str | Path | None = None) -> list[dict[str, Any]]:
    """완료·실행 중 작업의 partial.jsonl 에서 페르소나별 평가 행을 읽습니다."""
    if partial_jsonl_path:
        rows = load_partial_eval_rows(Path(partial_jsonl_path))
        if rows:
            return rows
    from nemotron_ab.campaign_assets import OUTPUT_JOBS

    job_dir = OUTPUT_JOBS / f"job_{job_id}"
    for candidate in (
        job_dir / "result" / f"job_{job_id}.partial.jsonl",
        job_dir / "partial.jsonl",
    ):
        rows = load_partial_eval_rows(candidate)
        if rows:
            return rows
    return []


def load_partial_eval_rows(path: Path) -> list[dict[str, Any]]:
    """페르소나별 LLM 평가 결과(partial.jsonl) 전체 행을 읽습니다."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def _synthesis_max_eval_json_chars() -> int:
    raw = os.environ.get(ENV_SYNTHESIS_MAX_EVAL_JSON_CHARS, "").strip()
    if not raw:
        return DEFAULT_SYNTHESIS_MAX_EVAL_JSON_CHARS
    try:
        return max(1000, int(raw))
    except ValueError:
        return DEFAULT_SYNTHESIS_MAX_EVAL_JSON_CHARS


def compact_row_for_synthesis(row: dict[str, Any]) -> dict[str, Any]:
    """종합 분석 프롬프트용 — 페르소나별 winner·점수·reason."""
    return {
        "persona_id": row.get("persona_id"),
        "age": row.get("age"),
        "bucket": row.get("bucket"),
        "winner": row.get("winner"),
        "weighted_score": row.get("weighted_score"),
        "confidence": row.get("confidence"),
        "reason": row.get("reason"),
    }


def build_persona_evaluations_payload(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """전체 표본을 JSON 직렬화 길이 상한 안에 넣습니다(행 단위로 tail 절단)."""
    compact = [compact_row_for_synthesis(r) for r in rows]
    meta: dict[str, Any] = {
        "total_rows": len(rows),
        "included_rows": len(compact),
        "truncated": False,
    }
    max_chars = _synthesis_max_eval_json_chars()
    while compact:
        payload = json.dumps(compact, ensure_ascii=False)
        if len(payload) <= max_chars:
            meta["included_rows"] = len(compact)
            return compact, meta
        compact = compact[:-1]
        meta["truncated"] = True
    meta["included_rows"] = 0
    return [], meta


def base_url_host_for_display(base_url: str) -> str:
    try:
        parsed = urlparse(base_url)
        if parsed.netloc:
            return parsed.netloc
    except Exception:  # noqa: BLE001
        pass
    return base_url


def build_aggregation_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    """종합 분석 프롬프트·UI용 집계 스냅샷."""
    key_reasons = report.get("key_reasons") or []
    if not isinstance(key_reasons, list):
        key_reasons = []
    return {
        "final_winner": report.get("final_winner"),
        "overall": report.get("overall"),
        "summary_by_bucket": report.get("summary_by_bucket"),
        "conditional_recommendation": report.get("conditional_recommendation"),
        "key_reasons": key_reasons,
    }


def build_synthesis_inputs_used(
    *,
    campaign: dict[str, Any],
    report: dict[str, Any],
    persona_evaluations: list[dict[str, Any]],
    persona_evaluations_meta: dict[str, Any],
    multimodal: bool,
) -> dict[str, Any]:
    """LLM에 실제 전달된 입력 스냅샷(리포트·UI「분석에 사용된 입력」)."""
    return {
        "context": str(campaign.get("context", "") or "").strip(),
        "text_a": str(campaign.get("text_a", "") or campaign.get("copy_a", "") or "").strip(),
        "text_b": str(campaign.get("text_b", "") or campaign.get("copy_b", "") or "").strip(),
        "multimodal": bool(multimodal),
        "aggregation": build_aggregation_snapshot(report),
        "persona_evaluations": persona_evaluations,
        "persona_evaluations_meta": persona_evaluations_meta,
    }


def build_synthesis_prompt(
    *,
    campaign: dict[str, Any],
    report: dict[str, Any],
    persona_evaluations: list[dict[str, Any]] | None = None,
    persona_eval_meta: dict[str, Any] | None = None,
    multimodal: bool = False,
) -> str:
    context = str(campaign.get("context", "") or "").strip() or "(맥락 없음)"
    text_a = str(campaign.get("text_a", "") or "").strip() or "(없음)"
    text_b = str(campaign.get("text_b", "") or "").strip() or "(없음)"
    has_images = payload_has_any_image(campaign)
    agg_payload = build_aggregation_snapshot(report)

    eval_rows, eval_meta = build_persona_evaluations_payload(persona_evaluations or [])
    eval_meta_out = {**(persona_eval_meta or {}), **eval_meta}

    lines = [
        "당신은 마케팅 리서치 리포트 작성자입니다.",
        "아래 [집계·핵심 인사이트]와 [페르소나별 평가 전체 표본](partial.jsonl)을 근거로 종합 분석을 작성하세요.",
        "- 집계 수치·표본 수·승률·최종 추천 Variant는 [집계·핵심 인사이트]의 값만 인용하세요(환각 금지).",
        "- 정성 해석·반복되는 근거·세그먼트별 뉘앙스는 [페르소나별 평가 전체 표본]의 reason·winner를 우선 반영하세요.",
        "- key_reasons는 요약이므로, 표본 전체와 충돌하면 표본 전체를 따르세요.",
        "- 출력은 오직 JSON 객체 하나만 (한국어).",
        "",
        f"[JSON 스키마 예시]\n{json.dumps(SYNTHESIS_JSON_SCHEMA_HINT, ensure_ascii=False, indent=2)}",
        "",
        f"[맥락]\n{context}",
        f"[텍스트 A]\n{text_a}",
        f"[텍스트 B]\n{text_b}",
    ]
    if multimodal and has_images:
        order: list[str] = []
        if isinstance(campaign.get("image_a"), dict) and str(campaign["image_a"].get("value", "")).strip():
            order.append("A")
        if isinstance(campaign.get("image_b"), dict) and str(campaign["image_b"].get("value", "")).strip():
            order.append("B")
        joined = ", ".join(order)
        lines.append(
            f"[시각 자료] 이 메시지 하단 이미지는 순서대로 안 {joined}입니다. "
            "시각적 차이 해석에 활용하되, 최종 추천 Variant는 집계 결과를 따르세요."
        )
    elif has_images:
        lines.append("[이미지] 작업에 이미지가 포함되었으나 본 호출에는 첨부되지 않았습니다.")
    else:
        lines.append("[이미지] 없음 (텍스트만)")
    lines.extend(
        [
            "",
            f"[집계·핵심 인사이트]\n{json.dumps(agg_payload, ensure_ascii=False, indent=2)}",
        ]
    )
    if eval_rows:
        lines.extend(
            [
                "",
                f"[페르소나별 평가 전체 표본] (meta: {json.dumps(eval_meta_out, ensure_ascii=False)})\n"
                f"{json.dumps(eval_rows, ensure_ascii=False, indent=2)}",
            ]
        )
    else:
        lines.append("")
        lines.append("[페르소나별 평가 전체 표본] (없음 — partial.jsonl을 읽지 못했습니다)")
    return "\n".join(lines)


def build_synthesis_message_content(
    *,
    campaign: dict[str, Any],
    report: dict[str, Any],
    persona_evaluations: list[dict[str, Any]] | None = None,
    persona_eval_meta: dict[str, Any] | None = None,
    image_max_dim: int | None = None,
) -> str | list[dict[str, Any]]:
    """텍스트 프롬프트 또는 멀티모달(텍스트+image_url) 메시지 본문."""
    use_multimodal = payload_has_any_image(campaign)
    text = build_synthesis_prompt(
        campaign=campaign,
        report=report,
        persona_evaluations=persona_evaluations,
        persona_eval_meta=persona_eval_meta,
        multimodal=use_multimodal,
    )
    if not use_multimodal:
        return text

    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for key in ("image_a", "image_b"):
        ref = campaign.get(key)
        if isinstance(ref, dict) and str(ref.get("value", "")).strip():
            url = image_ref_to_data_url(ref, max_dim=image_max_dim)
            content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def _normalize_synthesis_content(parsed: dict[str, Any]) -> dict[str, Any]:
    headline = str(parsed.get("headline", "") or "").strip()
    executive_summary = str(parsed.get("executive_summary", "") or "").strip()
    segment_notes = str(parsed.get("segment_notes", "") or "").strip()
    limitations = str(parsed.get("limitations", "") or "").strip()
    raw_items = parsed.get("action_items")
    action_items: list[str] = []
    if isinstance(raw_items, list):
        action_items = [str(x).strip() for x in raw_items if str(x).strip()]
    full_markdown = str(parsed.get("full_markdown", "") or "").strip()
    if not full_markdown:
        parts = []
        if headline:
            parts.append(f"## {headline}\n")
        if executive_summary:
            parts.append(executive_summary)
        if segment_notes:
            parts.append(f"\n### 세그먼트\n{segment_notes}")
        if action_items:
            parts.append("\n### 실행 제안\n" + "\n".join(f"- {a}" for a in action_items))
        if limitations:
            parts.append(f"\n### 한계\n{limitations}")
        full_markdown = "\n".join(parts).strip()
    return {
        "headline": headline or "종합 분석",
        "executive_summary": executive_summary,
        "segment_notes": segment_notes,
        "action_items": action_items,
        "limitations": limitations,
        "full_markdown": full_markdown,
    }


def run_synthesis_llm(
    *,
    campaign: dict[str, Any],
    report: dict[str, Any],
    llm_config: LLMConfig,
    persona_evaluations: list[dict[str, Any]] | None = None,
    persona_eval_meta: dict[str, Any] | None = None,
    image_max_dim: int | None = None,
) -> tuple[dict[str, Any], dict[str, int], bool]:
    from langchain_core.messages import HumanMessage

    message_content = build_synthesis_message_content(
        campaign=campaign,
        report=report,
        persona_evaluations=persona_evaluations,
        persona_eval_meta=persona_eval_meta,
        image_max_dim=image_max_dim,
    )
    used_multimodal = isinstance(message_content, list)
    llm = make_chat_llm(llm_config, response_format_json=True)
    try:
        resp = llm.invoke([HumanMessage(content=message_content)])
    except Exception:
        llm = make_chat_llm(llm_config, response_format_json=False)
        resp = llm.invoke([HumanMessage(content=message_content)])

    usage = extract_usage(resp)
    raw_content = resp.content
    if isinstance(raw_content, list):
        raw = " ".join(
            str(part.get("text", part) if isinstance(part, dict) else part) for part in raw_content
        ).strip()
    else:
        raw = (raw_content or "").strip()
    parsed = _extract_json_object(raw)
    content = _normalize_synthesis_content(parsed)
    return content, usage, used_multimodal


def synthesize_job_report(
    conn,
    job_id: int,
    *,
    body_base_url: str | None = None,
    body_model: str | None = None,
) -> dict[str, Any]:
    """완료 작업 리포트에 synthesis 블록을 생성·저장합니다."""
    job = db.fetch_job(conn, job_id)
    if job is None:
        raise ValueError("job not found")
    if str(job["status"]) != "completed":
        raise ValueError("completed 상태의 작업만 종합 분석할 수 있습니다")

    res = db.fetch_job_result(conn, job_id)
    if res is None:
        raise ValueError("job_results 행이 없습니다")

    report_path = Path(str(res["report_json_path"]))
    if not report_path.is_file():
        raise ValueError("report.json 파일이 없습니다")

    report_obj: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    report_section = report_obj.get("report")
    if not isinstance(report_section, dict):
        raise ValueError("report 블록이 없습니다")

    campaign = report_obj.get("campaign")
    if not isinstance(campaign, dict):
        raise ValueError("campaign 블록이 없습니다")

    payload = json.loads(job["payload_json"])
    cfg = resolve_synthesis_llm_config(
        body_base_url=body_base_url,
        body_model=body_model,
        job_payload=payload,
    )
    generated_at = datetime.now(timezone.utc).isoformat()

    image_max_dim: int | None = None
    image_max_dim_raw = payload.get("image_max_dim")
    if image_max_dim_raw is not None:
        try:
            image_max_dim = int(image_max_dim_raw)
        except (TypeError, ValueError):
            image_max_dim = None

    synthesis: dict[str, Any] = {
        "generated_at": generated_at,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "base_url_host": base_url_host_for_display(cfg.base_url),
        "multimodal": payload_has_any_image(campaign),
        "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "content": None,
        "error": None,
    }

    partial_path = Path(str(res["partial_jsonl_path"]))
    persona_rows = load_job_partial_eval_rows(job_id, partial_jsonl_path=partial_path)
    persona_eval_meta = {"partial_jsonl_path": str(partial_path)}
    eval_rows, eval_meta_out = build_persona_evaluations_payload(persona_rows)
    persona_eval_meta_merged = {**persona_eval_meta, **eval_meta_out}

    try:
        content, usage, used_multimodal = run_synthesis_llm(
            campaign=campaign,
            report=report_section,
            llm_config=cfg,
            persona_evaluations=persona_rows,
            persona_eval_meta=persona_eval_meta,
            image_max_dim=image_max_dim,
        )
        synthesis["content"] = content
        synthesis["tokens"] = usage
        synthesis["multimodal"] = used_multimodal
    except Exception as e:  # noqa: BLE001
        synthesis["error"] = str(e)
        report_obj["synthesis"] = synthesis
        report_path.write_text(json.dumps(report_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        raise ValueError(f"종합 분석 LLM 호출 실패: {e}") from e

    report_obj["synthesis"] = synthesis
    synthesis["persona_evaluations_meta"] = persona_eval_meta_merged
    synthesis["inputs_used"] = build_synthesis_inputs_used(
        campaign=campaign,
        report=report_section,
        persona_evaluations=eval_rows,
        persona_evaluations_meta=persona_eval_meta_merged,
        multimodal=used_multimodal,
    )
    eval_tokens = db.job_token_totals(conn, job_id)
    merged_usage = build_job_llm_usage(
        eval_tokens,
        synthesis_tokens=usage,
        synthesis_call_count=1,
    )
    report_obj["tokens"] = merged_usage
    report_path.write_text(json.dumps(report_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    _append_synthesis_to_md(report_path.with_suffix(".md"), synthesis, tokens=merged_usage)

    summary_patch = {
        "synthesis_headline": content.get("headline"),
        "synthesis_generated_at": generated_at,
        "synthesis_model": cfg.model,
        "tokens": merged_usage,
    }
    db.patch_job_result_summary(conn, job_id, summary_patch)

    db.add_notification(
        conn,
        job_id,
        "success",
        f"작업 #{job_id} 종합 분석 완료",
        str(content.get("headline", ""))[:200],
    )

    return {
        "status": "ok",
        "synthesis": synthesis,
        "synthesis_headline": content.get("headline"),
    }


def _append_synthesis_to_md(
    md_path: Path,
    synthesis: dict[str, Any],
    *,
    tokens: dict[str, Any] | None = None,
) -> None:
    if not md_path.is_file():
        return
    content = synthesis.get("content")
    if not isinstance(content, dict):
        return
    existing = md_path.read_text(encoding="utf-8")
    marker = "## Executive Synthesis"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip()
    syn_tokens = synthesis.get("tokens") if isinstance(synthesis.get("tokens"), dict) else {}
    lines = [
        "",
        "## Executive Synthesis",
        "",
        f"- generated_at: {synthesis.get('generated_at')}",
        f"- model: {synthesis.get('model')}",
    ]
    if syn_tokens:
        lines.append(
            f"- synthesis_tokens: total={int(syn_tokens.get('total_tokens', 0) or 0)}"
        )
    if tokens:
        lines.append(
            f"- job_total_tokens: {int(tokens.get('total_tokens', 0) or 0)} "
            f"(llm_calls={int(tokens.get('llm_call_count', 0) or 0)})"
        )
    lines.extend(
        [
            "",
            f"### {content.get('headline', '')}",
            "",
            str(content.get("executive_summary", "")),
        ]
    )
    items = content.get("action_items")
    if isinstance(items, list) and items:
        lines.append("")
        lines.append("### 실행 제안")
        for item in items:
            lines.append(f"- {item}")
    md_path.write_text(existing + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
