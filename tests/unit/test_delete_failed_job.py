"""완료·실패 작업 DB 삭제 API 로직 검증."""
from __future__ import annotations

import sqlite3

import pytest

from nemotron_ab import db


def test_delete_job_failed_removes_related_rows(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "fail-del", {"k": "v"}, status="failed")
    tid = db.insert_job_task(fresh_conn, jid, "llm_score", {"i": 0})
    db.fail_task(fresh_conn, tid, "err")
    db.add_notification(fresh_conn, jid, "error", "t", "m")

    db.delete_job(fresh_conn, jid)

    assert db.fetch_job(fresh_conn, jid) is None
    assert db.count_job_tasks(fresh_conn, jid) == 0
    assert db.fetch_job_result(fresh_conn, jid) is None


def test_delete_job_completed(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "done-del", {"k": "v"}, status="completed")
    db.add_notification(fresh_conn, jid, "success", "t", "m")

    db.delete_job(fresh_conn, jid)

    assert db.fetch_job(fresh_conn, jid) is None


def test_delete_job_rejects_running(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "run", {"k": "v"}, status="running")
    with pytest.raises(ValueError, match="완료 또는 실패"):
        db.delete_job(fresh_conn, jid)
    assert db.fetch_job(fresh_conn, jid) is not None


def test_delete_job_not_found(fresh_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not found"):
        db.delete_job(fresh_conn, 999_999)
