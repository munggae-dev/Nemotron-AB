import json
import sqlite3
from typing import Optional

from app import db
from app.services.validator_runner import run_validator


def process_one_job(conn: sqlite3.Connection) -> Optional[int]:
    job = db.claim_next_pending_job(conn)
    if job is None:
        return None
    job_id = int(job["id"])
    try:
        payload = json.loads(job["payload_json"])
        report_json, partial_jsonl, summary = run_validator(job_id=job_id, payload=payload)
        db.complete_job(
            conn=conn,
            job_id=job_id,
            report_json_path=str(report_json),
            partial_jsonl_path=str(partial_jsonl),
            summary=summary,
        )
        db.add_notification(
            conn=conn,
            job_id=job_id,
            n_type="success",
            title=f"작업 #{job_id} 완료",
            message=f"최종 추천: {summary['final_winner']}",
        )
    except Exception as e:  # noqa: BLE001
        db.fail_job(conn=conn, job_id=job_id, error_message=str(e))
        db.add_notification(
            conn=conn,
            job_id=job_id,
            n_type="error",
            title=f"작업 #{job_id} 실패",
            message=str(e),
        )
    return job_id


def run_worker_tick(conn: sqlite3.Connection, max_jobs: int = 1) -> int:
    processed = 0
    for _ in range(max_jobs):
        job_id = process_one_job(conn)
        if job_id is None:
            break
        processed += 1
    return processed
