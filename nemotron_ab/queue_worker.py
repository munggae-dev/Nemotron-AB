import json
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Optional, Set, Union

from nemotron_ab import db
from nemotron_ab.db_engine import DBConnection
from nemotron_ab.job_tasks_worker import process_one_task
from nemotron_ab.services.validator_runner import run_validator


WorkerTarget = Union[Path, str]


def _resolve_worker_target(conn) -> Optional[WorkerTarget]:
    """스레드 풀에서 새 커넥션을 만들 때 쓸 타깃을 결정.

    - sqlite3.Connection 이면 PRAGMA database_list 로 파일 경로 추출.
    - DBConnection wrapper 면 SA URL 문자열 (password 포함).
    """
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute("PRAGMA database_list")
        for _seq, name, file_path in cur.fetchall():
            if name == "main" and file_path:
                return Path(file_path)
        return None
    if isinstance(conn, DBConnection):
        try:
            return conn.engine.url.render_as_string(hide_password=False)
        except Exception:  # noqa: BLE001
            return None
    return None


def _process_one_task_with_fresh_conn(target: WorkerTarget) -> Optional[int]:
    c = db.get_conn(target)
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


def run_worker_loop(
    conn: sqlite3.Connection,
    task_parallelism: int = 1,
    poll_interval_sec: float = 2.0,
    stop_event: Optional[threading.Event] = None,
    on_processed=None,
) -> None:
    """풀을 한 번만 생성해 유지하면서 끝난 슬롯에 즉시 새 태스크를 투입하는 루프.

    - 슬롯 비면 즉시 다음 pending task를 풀에 submit (no wave 동기화)
    - 큐가 비면 process_one_job(레거시) fallback 1건 시도
    - 둘 다 없으면 poll_interval_sec 만큼 대기
    - stop_event가 set 되면 in-flight 완료 후 종료
    """
    tp = max(1, min(8, int(task_parallelism)))
    db_path = _resolve_worker_target(conn)
    if db_path is None or tp <= 1:
        while stop_event is None or not stop_event.is_set():
            processed = run_worker_tick(conn=conn, max_jobs=1, task_parallelism=1)
            if on_processed is not None and processed > 0:
                on_processed(processed)
            if processed == 0:
                if stop_event is not None and stop_event.wait(timeout=poll_interval_sec):
                    break
                elif stop_event is None:
                    time.sleep(poll_interval_sec)
        return

    inflight: Set[Future] = set()
    with ThreadPoolExecutor(max_workers=tp, thread_name_prefix="llm-task") as pool:
        while stop_event is None or not stop_event.is_set():
            while len(inflight) < tp:
                if stop_event is not None and stop_event.is_set():
                    break
                fut = pool.submit(_process_one_task_with_fresh_conn, db_path)
                inflight.add(fut)

            done, inflight = wait(inflight, timeout=poll_interval_sec, return_when=FIRST_COMPLETED)

            any_processed = False
            empty_slot = False
            for fut in done:
                try:
                    tid = fut.result()
                except Exception as e:  # noqa: BLE001
                    print(f"[worker] task worker raised: {e}", flush=True)
                    tid = None
                if tid is not None:
                    any_processed = True
                else:
                    empty_slot = True

            if any_processed and on_processed is not None:
                on_processed(len(done))

            if not done:
                continue

            if empty_slot and not any_processed:
                try:
                    job_id = process_one_job(conn)
                except Exception as e:  # noqa: BLE001
                    print(f"[worker] legacy job failed: {e}", flush=True)
                    job_id = None
                if job_id is None:
                    if stop_event is not None and stop_event.wait(timeout=poll_interval_sec):
                        break
                    elif stop_event is None:
                        time.sleep(poll_interval_sec)

        if inflight:
            for fut in as_completed(inflight):
                try:
                    fut.result()
                except Exception:  # noqa: BLE001
                    pass


def run_worker_tick(
    conn: sqlite3.Connection,
    max_jobs: int = 1,
    task_parallelism: int = 1,
) -> int:
    """job_tasks(LLM) 우선, 없으면 레거시 job 단위 처리.

    task_parallelism>1이면 태스크 처리 시 DB 경로별로 스레드 풀을 사용해
    동시에 여러 `llm_score` 태스크를 소비합니다(Ollama I/O 병렬).
    """
    processed = 0
    db_path = _resolve_worker_target(conn)
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
