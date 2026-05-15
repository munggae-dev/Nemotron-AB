"""모든 태스크가 실패했을 때 작업이 자동으로 'failed' 로 마감되는지 검증.

회귀 시나리오: 모델명을 잘못 입력해 모든 LLM 호출이 실패하면, 워커는 각 태스크를
db.fail_task 로 마감만 하고 finalize 가 누락돼 작업이 영원히 'running' 상태로
멈춰 있었다. 다음을 보장한다.

1. db.latest_failed_task_error 가 가장 최근 실패 사유를 반환한다.
2. try_finalize_job 는 진행 중 태스크가 없으면 작업을 'failed' 로 마감하고
   error_message 에 마지막 태스크 오류를 포함한다.
3. 진행 중 태스크가 남아 있으면 try_finalize_job 는 no-op 이다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nemotron_ab import db
from nemotron_ab.job_tasks_worker import try_finalize_job


@pytest.fixture(autouse=True)
def _isolate_output_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """다른 테스트/실행의 partial.jsonl 잔재가 finalize 결과를 오염시키지 않도록 격리."""
    from nemotron_ab import job_tasks_worker as jtw
    from nemotron_ab.services import validator_runner as vr

    out_base = tmp_path / "outputs" / "jobs"
    out_base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(vr, "OUTPUT_BASE", out_base)
    monkeypatch.setattr(jtw, "OUTPUT_BASE", out_base)
    return out_base


def _setup_job_with_failed_tasks(conn: sqlite3.Connection, *, n_failed: int, last_err: str) -> int:
    jid = db.enqueue_job(conn, "all-fail", {"k": "v"}, status="running")
    for i in range(n_failed):
        tid = db.insert_job_task(conn, jid, "llm_score", {"i": i})
        msg = last_err if i == n_failed - 1 else f"earlier-{i}"
        db.fail_task(conn, tid, msg)
    return jid


def test_latest_failed_task_error_returns_most_recent(fresh_conn: sqlite3.Connection) -> None:
    jid = _setup_job_with_failed_tasks(fresh_conn, n_failed=3, last_err="model not found: bogus-model")
    msg = db.latest_failed_task_error(fresh_conn, jid)
    assert msg is not None
    assert "bogus-model" in msg


def test_latest_failed_task_error_none_when_no_failure(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "ok", {"k": "v"}, status="pending")
    tid = db.insert_job_task(fresh_conn, jid, "llm_score", {"i": 0})
    db.complete_task(fresh_conn, tid, prompt_tokens=1, completion_tokens=2, total_tokens=3)
    assert db.latest_failed_task_error(fresh_conn, jid) is None


def test_try_finalize_job_marks_failed_when_all_tasks_failed(fresh_conn: sqlite3.Connection) -> None:
    jid = _setup_job_with_failed_tasks(
        fresh_conn,
        n_failed=4,
        last_err="attempts=3 last_err=model 'bogus-model' not found",
    )

    try_finalize_job(fresh_conn, jid)

    row = db.fetch_job(fresh_conn, jid)
    assert row is not None
    assert str(row["status"]) == "failed"
    err = str(row["error_message"] or "")
    assert "failed_tasks=4" in err
    assert "bogus-model" in err, f"실패 사유가 작업 메시지에 노출되지 않음: {err}"


def test_try_finalize_job_noop_when_running_tasks_remain(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "partial", {"k": "v"}, status="running")
    tid_running = db.insert_job_task(fresh_conn, jid, "llm_score", {"i": 0})
    fresh_conn.execute(
        "UPDATE job_tasks SET status='running' WHERE id=?",
        (tid_running,),
    )
    fresh_conn.commit()
    tid_failed = db.insert_job_task(fresh_conn, jid, "llm_score", {"i": 1})
    db.fail_task(fresh_conn, tid_failed, "boom")

    try_finalize_job(fresh_conn, jid)

    row = db.fetch_job(fresh_conn, jid)
    assert row is not None
    assert str(row["status"]) == "running", "진행 중 태스크가 남아 있으면 finalize 하면 안 된다"
