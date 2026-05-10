import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from app import db
from app.job_tasks_worker import process_one_task
from app.services.validator_runner import run_validator


def _sqlite_main_path(conn: sqlite3.Connection) -> Optional[Path]:
    cur = conn.execute("PRAGMA database_list")
    for _seq, name, file_path in cur.fetchall():
        if name == "main" and file_path:
            return Path(file_path)
    return None


def _process_one_task_with_fresh_conn(db_path: Path) -> Optional[int]:
    c = db.get_conn(db_path)
    db.init_db(c)
    try:
        return process_one_task(c)
    finally:
        c.close()


def process_one_job(conn: sqlite3.Connection) -> Optional[int]:
    job = db.claim_next_pending_job_legacy_only(conn)
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


def run_worker_tick(
    conn: sqlite3.Connection,
    max_jobs: int = 1,
    task_parallelism: int = 1,
) -> int:
    """job_tasks(LLM) 우선, 없으면 레거시 캠페인 단위 job 처리.

    task_parallelism>1이면 태스크 처리 시 DB 경로별로 스레드 풀을 사용해
    동시에 여러 `llm_score` 태스크를 소비합니다(Ollama I/O 병렬).
    """
    processed = 0
    db_path = _sqlite_main_path(conn)
    tp = max(1, min(8, int(task_parallelism)))

    for _ in range(max_jobs):
        if tp > 1 and db_path is not None:
            wave = 0
            with ThreadPoolExecutor(max_workers=tp) as pool:
                futures = [pool.submit(_process_one_task_with_fresh_conn, db_path) for _ in range(tp)]
                for fut in as_completed(futures):
                    tid = fut.result()
                    if tid is not None:
                        wave += 1
                        processed += 1
            if wave > 0:
                continue

        tid = process_one_task(conn)
        if tid is not None:
            processed += 1
            continue
        job_id = process_one_job(conn)
        if job_id is None:
            break
        processed += 1
    return processed
