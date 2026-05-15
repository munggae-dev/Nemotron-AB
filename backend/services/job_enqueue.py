"""Job 등록 후 이미지 정규화·LLM 태스크 큐 적재."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from backend.deps import get_conn
from nemotron_ab import db
from nemotron_ab.campaign_assets import normalize_job_payload_images
from nemotron_ab.job_tasks_worker import finalize_llm_enqueue_sync


async def finalize_llm_enqueue_async(job_id: int, title: str, payload: dict[str, Any]) -> None:
    """Chroma 검색 등 무거운 작업을 이벤트 루프를 막지 않도록 스레드에서 실행."""
    await asyncio.to_thread(finalize_llm_enqueue_sync, job_id, title, payload)


def finalize_payload_after_enqueue(job_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        normalized = normalize_job_payload_images(job_id, payload)
    except (FileNotFoundError, ValueError) as e:
        with get_conn() as conn:
            db.fail_job(conn, job_id, str(e))
        raise HTTPException(400, str(e)) from e
    with get_conn() as conn:
        db.update_job_payload(conn, job_id, normalized)
    return normalized
