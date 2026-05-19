from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from backend.deps import get_conn
from backend.schemas.jobs import JobCloneOptions, JobCreate
from backend.services.job_enqueue import finalize_llm_enqueue_async, finalize_payload_after_enqueue
from backend.services.job_payload import payload_from_create
from backend.services.job_progress import compute_job_progress, parse_summary_json
from backend.services.job_validation import (
    validate_image_in,
    validate_nemotron_persona_filter_enums,
    validate_variant_inputs,
)
from nemotron_ab import db
from nemotron_ab.campaign_assets import resolve_image_file_path, save_upload_to_staging
from nemotron_ab.job_tasks_worker import purge_job_output_dir, reaggregate_completed_job, try_finalize_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/assets", status_code=201)
async def upload_job_asset(file: UploadFile = File(...)) -> dict[str, str]:
    """이미지 업로드 → staging 참조. POST /jobs 시 image_a/image_b에 asset_ref로 넣습니다."""
    data = await file.read()
    try:
        ref = save_upload_to_staging(data, file.filename or "upload.bin")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"asset_ref": ref}


@router.get("/{job_id}/images/{variant}")
def get_job_variant_image(job_id: int, variant: str):
    """저장된 로컬 이미지 파일 또는 외부 URL(리다이렉트) 노출."""
    vlow = variant.strip().lower()
    if vlow not in ("a", "b"):
        raise HTTPException(404, "variant는 a 또는 b입니다")
    with get_conn() as conn:
        row = db.fetch_job_basic(conn, job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    payload = json.loads(row["payload_json"])
    ref = payload.get("image_a" if vlow == "a" else "image_b")
    if not isinstance(ref, dict):
        raise HTTPException(404, "이미지 없음")
    t = str(ref.get("type", ""))
    val = str(ref.get("value", "")).strip()
    if not val:
        raise HTTPException(404, "이미지 없음")
    if t == "url":
        return RedirectResponse(val)
    if t == "path":
        path = resolve_image_file_path(ref)
        if path is None:
            raise HTTPException(404, "파일 없음")
        return FileResponse(path)
    raise HTTPException(404, "이미지 없음")


@router.post("", status_code=201)
async def create_job(body: JobCreate, background_tasks: BackgroundTasks) -> dict[str, int]:
    validate_variant_inputs(body.text_a, body.image_a, "안 A")
    validate_variant_inputs(body.text_b, body.image_b, "안 B")
    validate_image_in(body.image_a)
    validate_image_in(body.image_b)
    if body.persona_filter.age_min > body.persona_filter.age_max:
        raise HTTPException(400, "age_min must be <= age_max")
    validate_nemotron_persona_filter_enums(body.persona_filter.model_dump())
    payload = payload_from_create(body)
    if body.use_llm_task_queue:
        with get_conn() as conn:
            job_id = db.enqueue_job(conn, body.title, payload, status="preparing")
        payload = finalize_payload_after_enqueue(job_id, payload)
        background_tasks.add_task(finalize_llm_enqueue_async, job_id, body.title, payload)
        return {"id": job_id}

    with get_conn() as conn:
        job_id = db.enqueue_job(conn, body.title, payload)
        db.add_notification(
            conn,
            job_id,
            "info",
            f"작업 #{job_id} 등록",
            "작업 큐에 추가되었습니다(레거시 서브프로세스 경로).",
        )
    finalize_payload_after_enqueue(job_id, payload)
    return {"id": job_id}


def _rows_to_job_dicts(rows: list[Any], *, omit_payload: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if omit_payload:
            d.pop("payload_json", None)
        d["report_summary"] = parse_summary_json(d.pop("summary_json", None))
        out.append(d)
    return out


@router.get("")
def list_jobs(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    q: str | None = None,
    omit_payload: bool = False,
    include_total: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    """작업 목록. `omit_payload=true`면 payload_json을 빼고 `report_summary`만 조합합니다(대역폭 절약).

    `include_total=true`이면 `{ items, total, limit, offset }` 형태로 반환합니다(페이지네이션 UI용).
    """
    with get_conn() as conn:
        rows = db.fetch_jobs_extended(
            conn,
            limit=limit,
            offset=offset,
            status=status,
            q=q,
            include_payload=not omit_payload,
        )
        items = _rows_to_job_dicts(rows, omit_payload=omit_payload)
        if not include_total:
            return items
        total = db.count_jobs(conn, status=status, q=q)
        return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{job_id}")
def get_job(job_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = db.fetch_job_with_result(conn, job_id)
        if row is None:
            raise HTTPException(404, "job not found")
        d = dict(row)
        if str(d.get("status") or "") in ("pending", "running"):
            breakdown_for_check = db.job_task_status_counts(conn, job_id)
            if (
                breakdown_for_check.get("total", 0) > 0
                and breakdown_for_check.get("pending", 0) == 0
                and breakdown_for_check.get("running", 0) == 0
            ):
                try:
                    try_finalize_job(conn, job_id)
                except Exception as e:  # noqa: BLE001
                    print(f"[get_job] finalize retry failed for job {job_id}: {e}", flush=True)
                row = db.fetch_job_with_result(conn, job_id)
                if row is not None:
                    d = dict(row)
        d["report_summary"] = parse_summary_json(d.pop("summary_json", None))
        d.pop("report_json_path", None)
        d.pop("result_partial_jsonl_path", None)
        breakdown = db.job_task_status_counts(conn, job_id)
        prog = compute_job_progress(
            str(d.get("status") or ""),
            str(d["started_at"]) if d.get("started_at") is not None else None,
            str(d["created_at"]) if d.get("created_at") is not None else None,
            breakdown,
        )
        if prog is not None:
            d["progress"] = prog
        d["tokens"] = db.job_token_totals(conn, job_id)
        return d


@router.delete("/{job_id}", status_code=200)
def delete_job_endpoint(job_id: int) -> dict[str, Any]:
    """완료·실패 작업을 큐·DB에서 영구 삭제합니다(복구 불가)."""
    with get_conn() as conn:
        try:
            db.delete_job(conn, job_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    purge_job_output_dir(job_id)
    return {"status": "ok", "id": job_id}


@router.post("/{job_id}/report/reaggregate", status_code=200)
def reaggregate_job_report(job_id: int) -> dict[str, Any]:
    """저장된 partial JSONL을 다시 집계해 리포트 파일·DB 요약을 갱신합니다."""
    with get_conn() as conn:
        try:
            summary = reaggregate_completed_job(conn, job_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"status": "ok", "report_summary": summary}


@router.post("/{job_id}/clone", status_code=201)
async def clone_job(
    job_id: int,
    body: JobCloneOptions | None,
    background_tasks: BackgroundTasks,
) -> dict[str, int]:
    """완료·실패·기타 모든 상태의 job을 원본 payload 그대로 새 job으로 복제 등록한다."""
    with get_conn() as conn:
        row = db.fetch_job_basic(conn, job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"원본 payload 파싱 실패: {e}") from e
    if not isinstance(payload, dict):
        raise HTTPException(400, "원본 payload가 객체 형식이 아닙니다")

    original_title = str(row["title"] or "")
    if body is not None and body.title is not None and body.title.strip():
        new_title = body.title.strip()
    else:
        new_title = f"{original_title} (복제)" if original_title else "복제된 작업"

    use_llm_task_queue = bool(payload.get("use_llm_task_queue", True))
    new_payload = dict(payload)
    new_payload["title"] = new_title

    with get_conn() as conn:
        if use_llm_task_queue:
            new_job_id = db.enqueue_job(conn, new_title, new_payload, status="preparing")
        else:
            new_job_id = db.enqueue_job(conn, new_title, new_payload)
            db.add_notification(
                conn,
                new_job_id,
                "info",
                f"작업 #{new_job_id} 등록",
                f"#{job_id}을(를) 복제했습니다.",
            )

    finalized_payload = finalize_payload_after_enqueue(new_job_id, new_payload)

    if use_llm_task_queue:
        background_tasks.add_task(
            finalize_llm_enqueue_async, new_job_id, new_title, finalized_payload
        )

    return {"id": new_job_id}


@router.get("/{job_id}/report")
def get_report(job_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        res = db.fetch_job_result(conn, job_id)
        if res is None:
            raise HTTPException(404, "report not available")
        path = Path(res["report_json_path"])
        if not path.exists():
            raise HTTPException(404, "report file missing")
        return json.loads(path.read_text(encoding="utf-8"))
