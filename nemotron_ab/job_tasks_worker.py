"""LLM 호출 단위(job_tasks) 워커: 페르소나별 태스크 처리 후 집계."""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nemotron_ab import db
from nemotron_ab.campaign_assets import normalize_job_payload_images
from nemotron_ab.langchain_eval import evaluate_persona_langchain
from nemotron_ab.llm_provider import resolve_llm_config
from nemotron_ab.prompt_profile import (
    default_max_persona_chars,
    resolve_prompt_profile,
)
from nemotron_ab.services.validator_runner import OUTPUT_BASE, _make_campaign_payload
from scripts import ab_validator as mv


def _job_dir(job_id: int) -> Path:
    return OUTPUT_BASE / f"job_{job_id}"


def _partial_path(job_id: int) -> Path:
    return _job_dir(job_id) / "partial.jsonl"


def purge_job_output_dir(job_id: int) -> None:
    """작업별 outputs/jobs/job_{id} 디렉터리를 제거합니다."""
    d = _job_dir(job_id)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


def _finalize_llm_personas_and_tasks(conn, job_id: int, payload: dict[str, Any]) -> None:
    """상태가 preparing인 작업만: Chroma 검색 → llm_score 태스크 적재 → status=pending."""
    from nemotron_ab.services.validator_runner import _retrieve_filtered_personas

    row = db.fetch_job(conn, job_id)
    if row is None or str(row["status"]) != "preparing":
        return

    max_personas = int(payload.get("max_personas") or 40)
    rows = _retrieve_filtered_personas(payload, max_personas=max_personas)
    if not rows:
        db.fail_job(conn, job_id, "필터 조건에 맞는 페르소나를 찾지 못했습니다.")
        db.add_notification(
            conn,
            job_id,
            "error",
            f"작업 #{job_id} 실패",
            "필터 조건에 맞는 페르소나를 찾지 못했습니다.",
        )
        return

    campaign = _make_campaign_payload(job_id, payload)[0]
    _job_dir(job_id).mkdir(parents=True, exist_ok=True)
    p = _partial_path(job_id)
    if p.exists():
        p.unlink()
    for persona_row in rows:
        db.insert_job_task(
            conn,
            job_id,
            "llm_score",
            {"persona_row": persona_row, "campaign": campaign},
        )

    db.transition_job_status(conn, job_id, from_status="preparing", to_status="pending")

    db.add_notification(
        conn,
        job_id,
        "info",
        f"작업 #{job_id} 등록",
        f"LLM 태스크 {len(rows)}건이 큐에 추가되었습니다.",
    )


def finalize_llm_enqueue_sync(job_id: int, title: str, payload: dict[str, Any]) -> None:
    """FastAPI BackgroundTasks용: 응답 반환 후 별도 연결로 준비 단계를 마친다."""
    path = db.default_sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_conn(path)
    db.init_db(conn)
    try:
        _finalize_llm_personas_and_tasks(conn, job_id, payload)
    finally:
        conn.close()


def enqueue_job_with_llm_tasks(conn, title: str, payload: dict[str, Any]) -> int:
    """동기 등록 경로: 즉시 검색·태스크까지 완료한다."""
    job_id = db.enqueue_job(conn, title, payload, status="preparing")
    try:
        payload = normalize_job_payload_images(job_id, payload)
        db.update_job_payload(conn, job_id, payload)
    except Exception as e:  # noqa: BLE001
        db.fail_job(conn, job_id, str(e))
        raise
    _finalize_llm_personas_and_tasks(conn, job_id, payload)
    return job_id


def _run_llm_score(task_row, conn) -> None:
    task_id = int(task_row["id"])
    job_id = int(task_row["job_id"])
    body = json.loads(task_row["payload_json"])
    persona_row = body["persona_row"]
    campaign = body["campaign"]

    job = db.fetch_job(conn, job_id)
    if job is None:
        db.fail_task(conn, task_id, "job not found")
        _maybe_finalize_job(conn, job_id)
        return
    payload = json.loads(job["payload_json"])
    db.start_job_running(conn, job_id)

    persona = mv.normalize_persona_row(persona_row, fallback_id=f"task-{task_id}")
    if persona is None:
        db.fail_task(conn, task_id, "persona normalize failed")
        _maybe_finalize_job(conn, job_id)
        return

    evaluator = str(payload.get("evaluator", "mock"))
    mw = mv.DEFAULT_METRIC_WEIGHTS.copy()
    seed = int(payload.get("seed", 42))
    llm_base_url = str(payload.get("llm_base_url") or "").strip() or None
    llm_model = str(payload.get("llm_model") or "").strip() or None
    image_max_dim_raw = payload.get("image_max_dim")
    image_max_dim: int | None = None
    if image_max_dim_raw is not None:
        try:
            image_max_dim = int(image_max_dim_raw)
        except (TypeError, ValueError):
            image_max_dim = None

    def _as_str_list(v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v]
        return None

    # prompt_profile 해석: compact 는 핵심 필드만 / reason 상한 / JSON 강제
    resolved = resolve_prompt_profile(
        payload.get("prompt_profile"),
        user_max_reason_chars=int(payload.get("max_reason_chars", 80)),
        user_response_format_json=bool(payload.get("response_format_json", False)),
        user_persona_fields=_as_str_list(payload.get("persona_fields_for_prompt")),
        user_persona_drop_fields=_as_str_list(payload.get("persona_drop_fields")),
    )
    persona_fields = resolved.persona_fields
    persona_drop_fields = resolved.persona_drop_fields
    max_reason = resolved.max_reason_chars
    response_format_json = resolved.response_format_json

    # 페르소나 JSON 길이 캡 (payload 우선, 미지정 시 환경 기본값)
    raw_persona_cap = payload.get("max_persona_chars")
    try:
        max_persona_chars = int(raw_persona_cap) if raw_persona_cap is not None else default_max_persona_chars()
    except (TypeError, ValueError):
        max_persona_chars = default_max_persona_chars()
    if max_persona_chars <= 0:
        max_persona_chars = default_max_persona_chars()

    max_attempts = int(payload.get("llm_retry_attempts", 3))
    infra_keywords = (
        "eof",
        "status code: 500",
        "status code: 502",
        "status code: 503",
        "status code: 504",
        "runner",
        "connection",
        "connection reset",
        "remote disconnected",
        "ggml",
        "timeout",
        "timed out",
    )

    r: dict[str, Any] | None = None
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            if evaluator == "mock":
                r = mv.evaluate_with_mock(persona, campaign, mw, seed=seed)
                score_a = mv.weighted_sum(r["scores"]["A"], mw)
                score_b = mv.weighted_sum(r["scores"]["B"], mw)
                r["weighted_score"] = {"A": score_a, "B": score_b}
                r["confidence"] = mv.confidence_from_margin(score_a, score_b)
            else:
                cfg = resolve_llm_config(base_url=llm_base_url, model=llm_model)
                r, usage = evaluate_persona_langchain(
                    persona=persona,
                    campaign=campaign,
                    metrics=mw,
                    max_reason_chars=max_reason,
                    llm_config=cfg,
                    image_max_dim=image_max_dim,
                    persona_fields=persona_fields,
                    persona_drop_fields=persona_drop_fields,
                    response_format_json=response_format_json,
                    max_persona_chars=max_persona_chars,
                )
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            if evaluator == "mock" or attempt >= max_attempts:
                break
            msg = str(e).lower()
            is_infra = any(k in msg for k in infra_keywords)
            delay = 5.0 if is_infra else 1.0
            print(
                f"[task-{task_id}] attempt {attempt}/{max_attempts} failed "
                f"({'infra' if is_infra else 'format'}): {e}; retry in {delay}s",
                flush=True,
            )
            time.sleep(delay)

    if r is None:
        db.fail_task(
            conn,
            task_id,
            f"attempts={max_attempts} last_err={last_err}",
        )
        _maybe_finalize_job(conn, job_id)
        return

    out = {
        "campaign_id": campaign["id"],
        "persona_id": persona.persona_id,
        "age": persona.age,
        "bucket": persona.bucket,
        "winner": r["winner"],
        "scores": r["scores"],
        "weighted_score": r["weighted_score"],
        "confidence": r["confidence"],
        "reason": r["reason"],
        "tokens": usage,
    }
    partial = _partial_path(job_id)
    partial.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")

    db.complete_task(
        conn,
        task_id,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
    )
    _maybe_finalize_job(conn, job_id)


def _rows_from_partial_file(path: Path) -> list[dict[str, Any]]:
    rows_for_agg: list[dict[str, Any]] = []
    if not path.exists():
        return rows_for_agg
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows_for_agg.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows_for_agg


def _persist_aggregated_report(
    conn,
    job_id: int,
    payload: dict[str, Any],
    campaign: dict[str, Any],
    rows_for_agg: list[dict[str, Any]],
    failed: int,
) -> dict[str, Any]:
    """partial 결과를 집계해 리포트 파일·job_results·jobs 완료 상태를 기록합니다."""
    mw = mv.DEFAULT_METRIC_WEIGHTS.copy()
    t0 = time.perf_counter()
    report = mv.aggregate_results(rows_for_agg, metric_weights=mw)
    elapsed = time.perf_counter() - t0
    total_tasks = len(rows_for_agg) + int(failed)
    funnel = {
        "persona_filter": payload.get("persona_filter", {}),
        "flow": {
            "selected_personas": total_tasks,
            "scored_personas": len(rows_for_agg),
            "failed_personas": int(failed),
        },
    }
    token_totals = db.job_token_totals(conn, job_id)
    report_obj = {
        "campaign": campaign,
        "profile": payload.get("profile", "small"),
        "seed": int(payload.get("seed", 42)),
        "warnings": ([f"failed_llm_tasks={failed}"] if failed else []),
        "runtime": {
            "elapsed_sec": elapsed,
            "peak_memory_mb": 0.0,
        },
        "tokens": token_totals,
        "funnel": funnel,
        "report": report,
    }

    out_dir = _job_dir(job_id) / "result"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_json = out_dir / f"job_{job_id}.report.json"
    partial_jsonl = out_dir / f"job_{job_id}.partial.jsonl"
    mv.write_json(report_json, report_obj)
    mv.write_text_report(
        out_dir / f"job_{job_id}.report.md",
        campaign=campaign,
        report=report,
        warnings=report_obj["warnings"],
        runtime=report_obj["runtime"],
    )
    partial_live = _partial_path(job_id)
    if partial_live.exists():
        shutil.copy2(partial_live, partial_jsonl)

    summary = {
        "final_winner": report["final_winner"],
        "overall": report["overall"],
        "key_reasons": report["key_reasons"],
        "runtime": report_obj["runtime"],
        "tokens": token_totals,
        "funnel": funnel,
    }
    db.complete_job(
        conn,
        job_id,
        report_json_path=str(report_json),
        partial_jsonl_path=str(partial_jsonl),
        summary=summary,
    )
    return summary


def reaggregate_completed_job(conn, job_id: int) -> dict[str, Any]:
    """완료된 작업의 partial JSONL을 다시 읽어 리포트·요약을 재생성합니다(API 재집계용)."""
    job = db.fetch_job(conn, job_id)
    if job is None:
        raise ValueError("job not found")
    if str(job["status"]) != "completed":
        raise ValueError("completed 상태의 작업만 재집계할 수 있습니다")

    res = db.fetch_job_result(conn, job_id)
    if res is None:
        raise ValueError("job_results 행이 없습니다")

    payload = json.loads(job["payload_json"])
    campaign = _make_campaign_payload(job_id, payload)[0]

    paths_try = []
    rp = res["partial_jsonl_path"]
    if rp:
        paths_try.append(Path(str(rp)))
    paths_try.append(_partial_path(job_id))

    rows_for_agg: list[dict[str, Any]] = []
    seen_partial_path: Path | None = None
    for p in paths_try:
        chunk = _rows_from_partial_file(p)
        if chunk:
            rows_for_agg = chunk
            seen_partial_path = p
            break

    if not rows_for_agg:
        raise ValueError(
            "집계할 partial 행이 없습니다(partial.jsonl 경로를 확인하세요)."
            f" 시도한 경로: {[str(p) for p in paths_try]}"
        )

    failed = db.count_job_tasks(conn, job_id, status="failed")
    summary = _persist_aggregated_report(conn, job_id, payload, campaign, rows_for_agg, failed)
    db.add_notification(
        conn,
        job_id,
        "info",
        f"작업 #{job_id} 리포트 재집계",
        f"최종 추천: {summary['final_winner']} (partial: {seen_partial_path})",
    )
    return summary


def _maybe_finalize_job(conn, job_id: int) -> None:
    pending = db.count_job_tasks(conn, job_id, status="pending")
    running = db.count_job_tasks(conn, job_id, status="running")
    if pending > 0 or running > 0:
        return

    failed = db.count_job_tasks(conn, job_id, status="failed")
    job = db.fetch_job(conn, job_id)
    if job is None:
        return
    payload = json.loads(job["payload_json"])
    campaign = _make_campaign_payload(job_id, payload)[0]
    partial = _partial_path(job_id)
    rows_for_agg = _rows_from_partial_file(partial)

    if not rows_for_agg:
        last_err = db.latest_failed_task_error(conn, job_id)
        base_msg = f"집계할 결과가 없습니다(failed_tasks={failed})."
        job_msg = f"{base_msg} 마지막 오류: {last_err}" if last_err else base_msg
        notif_msg = (
            f"집계할 유효한 페르소나 결과가 없습니다. 마지막 오류: {last_err}"
            if last_err
            else "집계할 유효한 페르소나 결과가 없습니다."
        )
        db.fail_job(conn, job_id, job_msg)
        db.add_notification(
            conn,
            job_id,
            "error",
            f"작업 #{job_id} 실패",
            notif_msg,
        )
        return

    summary = _persist_aggregated_report(conn, job_id, payload, campaign, rows_for_agg, failed)
    db.add_notification(
        conn,
        job_id,
        "success",
        f"작업 #{job_id} 완료",
        f"최종 추천: {summary['final_winner']}",
    )


def try_finalize_job(conn, job_id: int) -> None:
    """외부에서 호출 가능한 finalize 트리거. 진행 중인 태스크가 남아 있으면 no-op."""
    _maybe_finalize_job(conn, job_id)


def process_one_task(conn) -> int | None:
    """pending job_task 1건 처리. 없으면 None."""
    task = db.claim_next_pending_task(conn)
    if task is None:
        return None
    ttype = str(task["task_type"])
    if ttype == "llm_score":
        _run_llm_score(task, conn)
    else:
        db.fail_task(conn, int(task["id"]), f"unknown task_type: {ttype}")
    return int(task["id"])
