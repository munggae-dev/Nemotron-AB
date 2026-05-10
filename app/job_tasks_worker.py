"""LLM 호출 단위(job_tasks) 워커: 페르소나별 태스크 처리 후 집계."""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db
from app.campaign_assets import normalize_job_payload_images
from app.langchain_eval import evaluate_persona_ollama_langchain
from app.services.validator_runner import OUTPUT_BASE, _make_campaign_payload

from script import marketing_validator as mv


def _job_dir(job_id: int) -> Path:
    return OUTPUT_BASE / f"job_{job_id}"


def _partial_path(job_id: int) -> Path:
    return _job_dir(job_id) / "partial.jsonl"


def _finalize_llm_personas_and_tasks(conn, job_id: int, payload: Dict[str, Any]) -> None:
    """상태가 preparing인 작업만: Chroma 검색 → llm_score 태스크 적재 → status=pending."""
    from app.services.validator_runner import _retrieve_filtered_personas

    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
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

    conn.execute(
        "UPDATE jobs SET status='pending' WHERE id=? AND status='preparing'",
        (job_id,),
    )
    conn.commit()

    db.add_notification(
        conn,
        job_id,
        "info",
        f"작업 #{job_id} 등록",
        f"LLM 태스크 {len(rows)}건이 큐에 추가되었습니다.",
    )


def finalize_llm_enqueue_sync(job_id: int, title: str, payload: Dict[str, Any]) -> None:
    """FastAPI BackgroundTasks용: 응답 반환 후 별도 연결로 준비 단계를 마친다."""
    path = db.default_sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_conn(path)
    db.init_db(conn)
    try:
        _finalize_llm_personas_and_tasks(conn, job_id, payload)
    finally:
        conn.close()


def enqueue_job_with_llm_tasks(conn, title: str, payload: Dict[str, Any]) -> int:
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

    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        db.fail_task(conn, task_id, "job not found")
        return
    payload = json.loads(job["payload_json"])
    conn.execute(
        "UPDATE jobs SET status='running', started_at=COALESCE(started_at, datetime('now')) WHERE id=?",
        (job_id,),
    )
    conn.commit()

    persona = mv.normalize_persona_row(persona_row, fallback_id=f"task-{task_id}")
    if persona is None:
        db.fail_task(conn, task_id, "persona normalize failed")
        return

    evaluator = str(payload.get("evaluator", "mock"))
    mw = mv.DEFAULT_METRIC_WEIGHTS.copy()
    seed = int(payload.get("seed", 42))
    max_reason = int(payload.get("max_reason_chars", 80))
    ollama_model = str(payload.get("ollama_model", "gemma4:e4b-it-q4_K_M"))
    ollama_base = str(payload.get("ollama_base_url", "http://localhost:11434"))

    try:
        if evaluator == "mock":
            r = mv.evaluate_with_mock(persona, campaign, mw, seed=seed)
            score_a = mv.weighted_sum(r["scores"]["A"], mw)
            score_b = mv.weighted_sum(r["scores"]["B"], mw)
            r["weighted_score"] = {"A": score_a, "B": score_b}
            r["confidence"] = mv.confidence_from_margin(score_a, score_b)
        else:
            r = evaluate_persona_ollama_langchain(
                persona=persona,
                campaign=campaign,
                metrics=mw,
                max_reason_chars=max_reason,
                ollama_model=ollama_model,
                ollama_base_url=ollama_base,
            )
    except Exception as e:  # noqa: BLE001
        db.fail_task(conn, task_id, str(e))
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
    }
    partial = _partial_path(job_id)
    partial.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")

    db.complete_task(conn, task_id)
    _maybe_finalize_job(conn, job_id)


def _rows_from_partial_file(path: Path) -> List[Dict[str, Any]]:
    rows_for_agg: List[Dict[str, Any]] = []
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
    payload: Dict[str, Any],
    campaign: Dict[str, Any],
    rows_for_agg: List[Dict[str, Any]],
    failed: int,
) -> Dict[str, Any]:
    """partial 결과를 집계해 리포트 파일·job_results·jobs 완료 상태를 기록합니다."""
    mw = mv.DEFAULT_METRIC_WEIGHTS.copy()
    t0 = time.perf_counter()
    report = mv.aggregate_results(rows_for_agg, metric_weights=mw)
    elapsed = time.perf_counter() - t0
    report_obj = {
        "campaign": campaign,
        "profile": payload.get("profile", "small"),
        "seed": int(payload.get("seed", 42)),
        "warnings": ([f"failed_llm_tasks={failed}"] if failed else []),
        "runtime": {
            "elapsed_sec": elapsed,
            "peak_memory_mb": 0.0,
        },
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
    }
    db.complete_job(
        conn,
        job_id,
        report_json_path=str(report_json),
        partial_jsonl_path=str(partial_jsonl),
        summary=summary,
    )
    return summary


def reaggregate_completed_job(conn, job_id: int) -> Dict[str, Any]:
    """완료된 작업의 partial JSONL을 다시 읽어 리포트·요약을 재생성합니다(API 재집계용)."""
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
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

    rows_for_agg: List[Dict[str, Any]] = []
    seen_partial_path: Optional[Path] = None
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
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        return
    payload = json.loads(job["payload_json"])
    campaign = _make_campaign_payload(job_id, payload)[0]
    partial = _partial_path(job_id)
    rows_for_agg = _rows_from_partial_file(partial)

    if not rows_for_agg:
        db.fail_job(
            conn,
            job_id,
            f"집계할 결과가 없습니다(failed_tasks={failed}).",
        )
        db.add_notification(
            conn,
            job_id,
            "error",
            f"작업 #{job_id} 실패",
            "집계할 유효한 페르소나 결과가 없습니다.",
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


def process_one_task(conn) -> Optional[int]:
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
