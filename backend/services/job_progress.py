"""작업 진행률·ETA 추정."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any


def parse_sqlite_dt_utc(value: str | None) -> datetime | None:
    """SQLite `datetime('now')` 등 저장 시점을 UTC로 해석합니다."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(str(value).strip(), fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def utc_now_elapsed_since(ts_start: datetime | None) -> float | None:
    if ts_start is None:
        return None
    delta = datetime.now(UTC) - ts_start
    return max(0.0, delta.total_seconds())


def compute_job_progress(
    job_status: str,
    started_at: str | None,
    created_at: str | None,
    counts: dict[str, int],
) -> dict[str, Any] | None:
    """페르소나 LLM 태스크 진행률·남은 시간 추정(평균 페이스 기반)."""
    total = int(counts.get("total", 0))
    created_utc = parse_sqlite_dt_utc(created_at)
    elapsed_since_created_sec: float | None = utc_now_elapsed_since(created_utc)
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

    started_utc = parse_sqlite_dt_utc(started_at)
    elapsed_sec: float | None = utc_now_elapsed_since(started_utc)
    now_utc = datetime.now(UTC)

    avg_sec_per_task: float | None = None
    eta_sec: float | None = None
    eta_at: str | None = None
    note: str | None = None

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

    display_pct: float | None = 100.0 if job_status == "completed" else pct

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


def parse_summary_json(summary_json: str | None) -> dict[str, Any] | None:
    if not summary_json:
        return None
    try:
        out = json.loads(summary_json)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None
