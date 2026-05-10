"""FastAPI: jobs / notifications / reports / regions."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Mapping, Optional, Union

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import db
from app.campaign_assets import (
    normalize_job_payload_images,
    resolve_image_file_path,
    save_upload_to_staging,
    validate_asset_ref_exists,
)
from app.job_tasks_worker import finalize_llm_enqueue_sync, reaggregate_completed_job
from app.persona_filter_schema import (
    FILTER_ENUM_LOOKUP,
    FILTER_ENUMS_FOR_META,
    FIELD_LABEL_KO,
)
from app.regions import KOREA_REGIONS

def _db_path() -> Path:
    return db.default_sqlite_path()


@contextmanager
def get_conn() -> Generator:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_conn(path)
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


class PersonaFilterIn(BaseModel):
    """Nemotron-Personas-Korea 벡터DB 메타 및 시·군·구 필터(빈 문자열은 미적용)."""

    sex: str = "all"
    age_min: int = Field(20, ge=19, le=59)
    age_max: int = Field(50, ge=19, le=59)
    province: str = ""
    district: str = ""
    marital_status: str = ""
    education_level: str = ""
    family_type: str = ""
    housing_type: str = ""
    military_status: str = ""
    occupation_contains: str = Field("", max_length=80)


class ImageRefIn(BaseModel):
    """업로드 선행 시 POST /jobs/assets 로 받은 staging 참조, 또는 공개 https URL."""

    type: str  # url | asset_ref
    value: str


class JobCreate(BaseModel):
    title: str = "신규 카피 검증"
    copy_a: str = ""
    copy_b: str = ""
    image_a: Optional[ImageRefIn] = None
    image_b: Optional[ImageRefIn] = None
    product: str = ""
    category: str = ""
    tone: str = ""
    goal: str = ""
    description: str = ""
    profile: str = "small"
    evaluator: str = "mock"
    ollama_model: str = "gemma4:e4b-it-q4_K_M"
    ollama_base_url: str = "http://localhost:11434"
    max_personas: int = Field(24, ge=8, le=200)
    retrieval_k_per_bucket: int = Field(80, ge=20, le=500)
    eval_concurrency: int = Field(2, ge=1, le=8)
    seed: int = 42
    max_reason_chars: int = 80
    use_llm_task_queue: bool = True
    persona_filter: PersonaFilterIn


def _optional_image_payload(ref: Optional[ImageRefIn]) -> Optional[Dict[str, str]]:
    if ref is None:
        return None
    t = ref.type.strip()
    v = ref.value.strip()
    if not v:
        return None
    if t not in ("url", "asset_ref"):
        raise HTTPException(400, "image_a/image_b.type은 url 또는 asset_ref여야 합니다")
    return {"type": t, "value": v}


def _validate_variant_images(copy_s: str, img: Optional[ImageRefIn], label: str) -> None:
    has_copy = bool(copy_s.strip())
    has_img = img is not None and bool(img.value.strip())
    if not has_copy and not has_img:
        raise HTTPException(400, f"{label}에는 카피 또는 이미지 중 하나 이상 필요합니다")


def _validate_image_in(ref: Optional[ImageRefIn]) -> None:
    if ref is None or not ref.value.strip():
        return
    if ref.type.strip() == "url":
        v = ref.value.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise HTTPException(400, "이미지 URL은 http:// 또는 https:// 로 시작해야 합니다")
    elif ref.type.strip() == "asset_ref":
        try:
            validate_asset_ref_exists(ref.value.strip())
        except FileNotFoundError as e:
            raise HTTPException(400, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    else:
        raise HTTPException(400, "image type은 url 또는 asset_ref만 허용됩니다")


def _validate_nemotron_persona_filter_enums(pf: Mapping[str, Any]) -> None:
    for key, allowed in FILTER_ENUM_LOOKUP.items():
        v = str(pf.get(key, "") or "").strip()
        if v and v not in allowed:
            label = FIELD_LABEL_KO.get(key, key)
            raise HTTPException(
                400,
                f'persona_filter "{label}" 값이 허용 목록에 없습니다. '
                "GET /meta/persona-filters 의 options 를 사용하세요.",
            )


def _payload_from_create(body: JobCreate) -> Dict[str, Any]:
    img_a = _optional_image_payload(body.image_a)
    img_b = _optional_image_payload(body.image_b)
    return {
        "title": body.title,
        "copy_a": body.copy_a.strip(),
        "copy_b": body.copy_b.strip(),
        "image_a": img_a,
        "image_b": img_b,
        "product": body.product.strip(),
        "category": body.category.strip(),
        "tone": body.tone.strip(),
        "goal": body.goal.strip(),
        "description": body.description.strip(),
        "profile": body.profile,
        "evaluator": body.evaluator,
        "ollama_model": body.ollama_model.strip(),
        "ollama_base_url": body.ollama_base_url.rstrip("/"),
        "max_personas": body.max_personas,
        "retrieval_k_per_bucket": body.retrieval_k_per_bucket,
        "eval_concurrency": body.eval_concurrency,
        "seed": body.seed,
        "max_reason_chars": body.max_reason_chars,
        "persona_filter": body.persona_filter.model_dump(),
    }


def _parse_sqlite_dt_utc(value: Optional[str]) -> Optional[datetime]:
    """SQLite `datetime('now')` 등 저장 시점을 UTC로 해석합니다(표준 naive 시각 문자열은 UTC 로 가정).

    과거 버그: 로컬 `datetime.now()`와 naive 문자열 비교 시 타임존 오프셋만큼 경과·ETA가 틀어짐."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(str(value).strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _utc_now_elapsed_since(ts_start: Optional[datetime]) -> Optional[float]:
    if ts_start is None:
        return None
    delta = datetime.now(timezone.utc) - ts_start
    return max(0.0, delta.total_seconds())


def _compute_job_progress(
    job_status: str,
    started_at: Optional[str],
    created_at: Optional[str],
    counts: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    """페르소나 LLM 태스크 진행률·남은 시간 추정(평균 페이스 기반)."""
    total = int(counts.get("total", 0))
    created_utc = _parse_sqlite_dt_utc(created_at)
    elapsed_since_created_sec: Optional[float] = _utc_now_elapsed_since(created_utc)
    pending = int(counts.get("pending", 0))
    running = int(counts.get("running", 0))
    completed = int(counts.get("completed", 0))
    failed = int(counts.get("failed", 0))
    remaining_work = pending + running

    if total == 0:
        if job_status == "preparing":
            return {
                "phase": "preparing",
                "label": "페르소나 매칭·태스크 생성",
                "detail": "벡터 검색으로 표본을 고르고 평가 단위를 큐에 넣는 중입니다.",
                "tasks": {"total": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0},
                "percent": None,
                "elapsed_sec": None,
                "elapsed_since_created_sec": round(elapsed_since_created_sec, 2)
                if elapsed_since_created_sec is not None
                else None,
                "avg_sec_per_task": None,
                "eta_sec": None,
                "eta_at": None,
                "note": None,
            }
        return None

    pct = round(100.0 * completed / total, 1) if total else 0.0
    if job_status == "completed":
        phase = "done"
        label = "완료"
    elif job_status == "failed":
        phase = "failed"
        label = "실패/중단"
    elif job_status == "preparing":
        phase = "preparing"
        label = "매칭·큐 준비"
    elif completed == 0 and running == 0 and pending == total:
        phase = "queued"
        label = "평가 대기"
    else:
        phase = "llm_scoring"
        label = "페르소나별 LLM 평가"

    parts = [f"{completed}/{total}건 완료"]
    if pending:
        parts.append(f"대기 {pending}")
    if running:
        parts.append(f"실행 중 {running}")
    if failed:
        parts.append(f"실패 {failed}")
    detail = " · ".join(parts)

    started_utc = _parse_sqlite_dt_utc(started_at)
    elapsed_sec: Optional[float] = _utc_now_elapsed_since(started_utc)
    now_utc = datetime.now(timezone.utc)

    avg_sec_per_task: Optional[float] = None
    eta_sec: Optional[float] = None
    eta_at: Optional[str] = None
    note: Optional[str] = None

    if failed > 0 and job_status not in ("completed", "failed"):
        note = "일부 태스크가 실패했습니다. 예상 시간은 남은 정상 분량 기준이며 실제와 다를 수 있습니다."

    if (
        job_status not in ("completed", "failed")
        and completed >= 1
        and elapsed_sec is not None
        and elapsed_sec > 0.5
        and remaining_work > 0
    ):
        avg_sec_per_task = elapsed_sec / completed
        eta_sec = remaining_work * avg_sec_per_task
        cap = 7 * 24 * 3600
        if eta_sec > cap:
            eta_sec = None
            note = (note + " " if note else "") + "남은 시간 추정이 불안정해 표시하지 않습니다."
        else:
            eta_at = (now_utc + timedelta(seconds=eta_sec)).replace(microsecond=0).isoformat(timespec="seconds")

    display_pct: Optional[float] = 100.0 if job_status == "completed" else pct

    return {
        "phase": phase,
        "label": label,
        "detail": detail,
        "tasks": {
            "total": total,
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
        },
        "percent": display_pct,
        "elapsed_sec": round(elapsed_sec, 2) if elapsed_sec is not None else None,
        "elapsed_since_created_sec": round(elapsed_since_created_sec, 2)
        if elapsed_since_created_sec is not None
        else None,
        "avg_sec_per_task": round(avg_sec_per_task, 2) if avg_sec_per_task is not None else None,
        "eta_sec": round(eta_sec, 1) if eta_sec is not None else None,
        "eta_at": eta_at,
        "note": note,
    }


def _parse_summary_json(summary_json: Optional[str]) -> Optional[Dict[str, Any]]:
    if not summary_json:
        return None
    try:
        out = json.loads(summary_json)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


app = FastAPI(title="Nemotron Marketing API", version="0.1.0")
_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/meta/regions")
def meta_regions() -> Dict[str, List[str]]:
    return KOREA_REGIONS


@app.get("/meta/persona-filters")
def meta_persona_filters() -> Dict[str, Any]:
    """Nemotron-Personas-Korea 기반 벡터DB 필터 선택지(폼 채우기용)."""
    enum_fields = []
    for key, opt_list in FILTER_ENUMS_FOR_META.items():
        enum_fields.append(
            {
                "key": key,
                "label": FIELD_LABEL_KO.get(key, key),
                "options": [{"value": o, "label": o} for o in opt_list],
            }
        )
    return {
        "dataset": "nvidia/Nemotron-Personas-Korea",
        "age_range_note": "이 앱 데이터 파이프는 만 19~59 레코드를 사용합니다.",
        "enum_fields": enum_fields,
        "occupation_contains": {"max_chars": 80},
        "vectordb_hint": (
            "혼인·학력 등 메타는 script/build_vectordb.py 재생성 후 persona_db에 반영됩니다. "
            "이전 DB는 해당 필터 사용 시 결과가 비거나 무시될 수 있습니다."
        ),
    }


@app.get("/meta/queue-stats")
def meta_queue_stats() -> Dict[str, Union[int, Dict[str, int]]]:
    """작업 상태별 건수(대시보드 KPI용)."""
    with get_conn() as conn:
        by_status = db.queue_status_counts(conn)
        total = sum(by_status.values())
        return {"total": total, "by_status": by_status}


async def _finalize_llm_enqueue_async(job_id: int, title: str, payload: Dict[str, Any]) -> None:
    """Chroma 검색 등 무거운 작업을 이벤트 루프를 막지 않도록 스레드에서 실행."""
    await asyncio.to_thread(finalize_llm_enqueue_sync, job_id, title, payload)


def _finalize_payload_after_enqueue(job_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        normalized = normalize_job_payload_images(job_id, payload)
    except (FileNotFoundError, ValueError) as e:
        with get_conn() as conn:
            db.fail_job(conn, job_id, str(e))
        raise HTTPException(400, str(e)) from e
    with get_conn() as conn:
        db.update_job_payload(conn, job_id, normalized)
    return normalized


@app.post("/jobs/assets", status_code=201)
async def upload_job_asset(file: UploadFile = File(...)) -> Dict[str, str]:
    """이미지 업로드 → staging 참조. POST /jobs 시 image_a/image_b에 asset_ref로 넣습니다."""
    data = await file.read()
    try:
        ref = save_upload_to_staging(data, file.filename or "upload.bin")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"asset_ref": ref}


@app.get("/jobs/{job_id}/images/{variant}")
def get_job_variant_image(job_id: int, variant: str):
    """저장된 로컬 이미지 파일 또는 외부 URL(리다이렉트) 노출."""
    vlow = variant.strip().lower()
    if vlow not in ("a", "b"):
        raise HTTPException(404, "variant는 a 또는 b입니다")
    with get_conn() as conn:
        row = conn.execute("SELECT id, payload_json FROM jobs WHERE id=?", (job_id,)).fetchone()
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


@app.post("/jobs", status_code=201)
async def create_job(body: JobCreate, background_tasks: BackgroundTasks) -> Dict[str, int]:
    _validate_variant_images(body.copy_a, body.image_a, "안 A")
    _validate_variant_images(body.copy_b, body.image_b, "안 B")
    _validate_image_in(body.image_a)
    _validate_image_in(body.image_b)
    if body.persona_filter.age_min > body.persona_filter.age_max:
        raise HTTPException(400, "age_min must be <= age_max")
    _validate_nemotron_persona_filter_enums(body.persona_filter.model_dump())
    payload = _payload_from_create(body)
    if body.use_llm_task_queue:
        with get_conn() as conn:
            job_id = db.enqueue_job(conn, body.title, payload, status="preparing")
        payload = _finalize_payload_after_enqueue(job_id, payload)
        background_tasks.add_task(_finalize_llm_enqueue_async, job_id, body.title, payload)
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
    _finalize_payload_after_enqueue(job_id, payload)
    return {"id": job_id}


@app.get("/jobs")
def list_jobs(
    limit: int = 200,
    status: Optional[str] = None,
    q: Optional[str] = None,
    omit_payload: bool = False,
) -> List[Dict[str, Any]]:
    """작업 목록. `omit_payload=true`면 payload_json을 빼고 `report_summary`만 조합합니다(대역폭 절약)."""
    with get_conn() as conn:
        if omit_payload:
            rows = db.fetch_jobs_extended(conn, limit=limit, status=status, q=q, include_payload=False)
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                d["report_summary"] = _parse_summary_json(d.pop("summary_json", None))
                out.append(d)
            return out
        rows = db.fetch_jobs_extended(conn, limit=limit, status=status, q=q, include_payload=True)
        out2: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["report_summary"] = _parse_summary_json(d.pop("summary_json", None))
            out2.append(d)
        return out2


@app.get("/jobs/{job_id}")
def get_job(job_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        row = db.fetch_job_with_result(conn, job_id)
        if row is None:
            raise HTTPException(404, "job not found")
        d = dict(row)
        d["report_summary"] = _parse_summary_json(d.pop("summary_json", None))
        d.pop("report_json_path", None)
        d.pop("result_partial_jsonl_path", None)
        breakdown = db.job_task_status_counts(conn, job_id)
        prog = _compute_job_progress(
            str(d.get("status") or ""),
            str(d["started_at"]) if d.get("started_at") is not None else None,
            str(d["created_at"]) if d.get("created_at") is not None else None,
            breakdown,
        )
        if prog is not None:
            d["progress"] = prog
        return d


@app.post("/jobs/{job_id}/report/reaggregate", status_code=200)
def reaggregate_job_report(job_id: int) -> Dict[str, Any]:
    """저장된 partial JSONL을 다시 집계해 리포트 파일·DB 요약을 갱신합니다."""
    with get_conn() as conn:
        try:
            summary = reaggregate_completed_job(conn, job_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"status": "ok", "report_summary": summary}


@app.get("/jobs/{job_id}/report")
def get_report(job_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        res = db.fetch_job_result(conn, job_id)
        if res is None:
            raise HTTPException(404, "report not available")
        path = Path(res["report_json_path"])
        if not path.exists():
            raise HTTPException(404, "report file missing")
        return json.loads(path.read_text(encoding="utf-8"))


@app.get("/notifications")
def list_notifications(limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = db.fetch_notifications(conn, limit=limit)
        return [dict(r) for r in rows]


@app.get("/notifications/unread-count")
def unread_count() -> Dict[str, int]:
    with get_conn() as conn:
        return {"count": db.unread_notification_count(conn)}


@app.patch("/notifications/{notification_id}/read")
def mark_read(notification_id: int) -> Dict[str, str]:
    with get_conn() as conn:
        db.mark_notification_read(conn, notification_id)
    return {"status": "ok"}
