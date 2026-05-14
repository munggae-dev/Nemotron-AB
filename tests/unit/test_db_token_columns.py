"""V2: job_tasks 토큰 컬럼 + 레거시 DB 마이그레이션 + 집계.

토큰 추적 기능의 데이터 계층 회귀를 막는다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nemotron_ab import db


def test_init_db_creates_token_columns(fresh_conn: sqlite3.Connection) -> None:
    cur = fresh_conn.execute("PRAGMA table_info(job_tasks)")
    cols = {row[1]: row[2] for row in cur.fetchall()}
    for col in ("prompt_tokens", "completion_tokens", "total_tokens"):
        assert col in cols, f"missing column {col}"
        assert cols[col] == "INTEGER", f"wrong type for {col}: {cols[col]}"


def test_job_token_totals_empty(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "empty", {"k": "v"}, status="pending")
    totals = db.job_token_totals(fresh_conn, jid)
    assert totals == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "task_count": 0,
    }


def test_complete_task_persists_tokens(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "one", {"k": "v"}, status="pending")
    tid = db.insert_job_task(
        fresh_conn,
        jid,
        "llm_score",
        {"persona_row": {"persona_id": "p1"}, "campaign": {"id": "c1"}},
    )
    db.complete_task(
        fresh_conn,
        tid,
        prompt_tokens=120,
        completion_tokens=45,
        total_tokens=165,
    )
    totals = db.job_token_totals(fresh_conn, jid)
    assert totals == {
        "prompt_tokens": 120,
        "completion_tokens": 45,
        "total_tokens": 165,
        "task_count": 1,
    }


def test_job_token_totals_aggregates_multiple_tasks(fresh_conn: sqlite3.Connection) -> None:
    jid = db.enqueue_job(fresh_conn, "agg", {"k": "v"}, status="pending")
    for usage in [(100, 30, 130), (200, 50, 250), (50, 10, 60)]:
        tid = db.insert_job_task(fresh_conn, jid, "llm_score", {"i": 1})
        db.complete_task(
            fresh_conn,
            tid,
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            total_tokens=usage[2],
        )
    totals = db.job_token_totals(fresh_conn, jid)
    assert totals == {
        "prompt_tokens": 350,
        "completion_tokens": 90,
        "total_tokens": 440,
        "task_count": 3,
    }


def test_init_db_migrates_legacy_job_tasks(tmp_path: Path) -> None:
    """토큰 컬럼이 없던 구 스키마의 DB 를 열어도 init_db 가 ALTER 로 추가해야 한다."""
    legacy = tmp_path / "legacy.sqlite3"
    raw = sqlite3.connect(str(legacy))
    raw.executescript(
        """
        CREATE TABLE job_tasks (
            id INTEGER PRIMARY KEY,
            job_id INT,
            task_type TEXT,
            payload_json TEXT,
            status TEXT
        );
        """
    )
    raw.commit()
    raw.close()

    conn = db.get_conn(legacy)
    db.init_db(conn)
    try:
        cur = conn.execute("PRAGMA table_info(job_tasks)")
        cols = [row[1] for row in cur.fetchall()]
        for col in ("prompt_tokens", "completion_tokens", "total_tokens"):
            assert col in cols, f"legacy migration missed {col}"
    finally:
        conn.close()
