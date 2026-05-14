"""Phase 3.2: Postgres backend wrapper smoke test.

이 테스트는 `DATABASE_URL=postgresql+psycopg://…` 가 설정되고 psycopg 가
설치된 환경에서만 동작한다. CI 또는 로컬에서 다음과 같이 실행:

    docker compose --profile postgres up -d postgres
    export DATABASE_URL='postgresql+psycopg://nemotron:nemotron@127.0.0.1:5432/nemotron'
    pip install -e .[postgres]
    pytest -m needs_postgres tests/integration/test_db_postgres.py
"""
from __future__ import annotations

import os

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.needs_postgres]


def _pg_available() -> bool:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url.lower().startswith(("postgresql", "postgres")):
        return False
    try:
        import psycopg  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


pytest_skip_reason = "DATABASE_URL 이 postgres 가 아니거나 psycopg 미설치"


@pytest.fixture(autouse=True)
def _skip_if_no_pg() -> None:
    if not _pg_available():
        pytest.skip(pytest_skip_reason)


def _drop_all_tables(conn) -> None:
    for tbl in ("job_tasks", "job_results", "notifications", "jobs"):
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
        except Exception:  # noqa: BLE001
            pass
    conn.commit()


def test_init_and_crud_on_postgres() -> None:
    """PG 위에서 init_db / enqueue_job / fetch / token aggregation 까지 동작."""
    from nemotron_ab import db
    from nemotron_ab.db_engine import DBConnection

    conn = db.get_conn()
    assert isinstance(conn, DBConnection), "PG URL 에선 wrapper 가 반환되어야 함"
    try:
        _drop_all_tables(conn)
        db.init_db(conn)

        jid = db.enqueue_job(conn, "pg-smoke", {"k": "v"}, status="pending")
        assert isinstance(jid, int) and jid > 0

        row = db.fetch_job(conn, jid)
        assert row is not None
        assert row["title"] == "pg-smoke"
        assert row["status"] == "pending"

        # 태스크 인서트 + 토큰 누적
        for t in range(3):
            tid = db.insert_job_task(conn, jid, "llm_score", {"i": t})
            db.complete_task(
                conn,
                tid,
                prompt_tokens=10 * (t + 1),
                completion_tokens=2 * (t + 1),
                total_tokens=12 * (t + 1),
            )
        totals = db.job_token_totals(conn, jid)
        assert totals["prompt_tokens"] == 10 + 20 + 30
        assert totals["completion_tokens"] == 2 + 4 + 6
        assert totals["total_tokens"] == 12 + 24 + 36
        assert totals["task_count"] == 3

        # 조건부 전이
        ok = db.transition_job_status(conn, jid, from_status="pending", to_status="running")
        assert ok
        # 한 번 더는 실패 (이미 running)
        again = db.transition_job_status(conn, jid, from_status="pending", to_status="running")
        assert not again

        # complete_job → ON CONFLICT 경로 검증 (두 번 호출해도 멱등)
        db.complete_job(
            conn=conn,
            job_id=jid,
            report_json_path="/tmp/r.json",
            partial_jsonl_path="/tmp/p.jsonl",
            summary={"final_winner": "A"},
        )
        db.complete_job(
            conn=conn,
            job_id=jid,
            report_json_path="/tmp/r2.json",
            partial_jsonl_path="/tmp/p2.jsonl",
            summary={"final_winner": "B"},
        )
        res = db.fetch_job_result(conn, jid)
        assert res is not None
        assert str(res["report_json_path"]) == "/tmp/r2.json"
    finally:
        try:
            _drop_all_tables(conn)
        finally:
            conn.close()
