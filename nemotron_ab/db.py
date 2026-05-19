import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Union

from nemotron_ab.db_engine import (
    ENV_DATABASE_URL,
    DBConnection,
    is_sqlite,
    make_db_connection,
    make_sqlite_connection,
    resolve_database_url,
    sqlite_path_from_url,
)
from nemotron_ab.paths import resolve_sqlite_file_path

# 호출부 타입 힌트 호환을 위해 별칭으로 노출. 실제로는 sqlite3.Connection 또는 DBConnection.
ConnectionLike = Union[sqlite3.Connection, DBConnection]


def _fetch_inserted_id(cur: Any) -> int:
    """INSERT … RETURNING id 결과를 안전하게 추출.

    - native sqlite3.Cursor: RETURNING row 를 fetchone 으로 *반드시* 소비해야
      이어서 ``commit()`` 이 가능하다 ("SQL statements in progress" 회피).
    - DBConnection._CursorView: wrapper 가 RETURNING 발견 시 이미 row 를
      소비하고 ``lastrowid`` 에 저장해 둠 — 그땐 lastrowid 폴백.
    """
    new_id: int | None = None
    try:
        row = cur.fetchone()
        if row is not None:
            new_id = int(row[0])
    except Exception:  # noqa: BLE001
        new_id = None
    if new_id is None:
        rid = getattr(cur, "lastrowid", None)
        if rid is not None:
            try:
                new_id = int(rid)
            except Exception:  # noqa: BLE001
                new_id = None
    return int(new_id or 0)


def default_sqlite_path() -> Path:
    """환경변수 APP_SQLITE_PATH 또는 저장소 기본 app/app.sqlite3.

    상대 경로는 실행 cwd 가 아니라 저장소 루트 기준으로 해석한다.
    참고: 우선순위가 더 높은 `DATABASE_URL` 이 sqlite 이면 그 URL 경로를 반환한다.
    """
    env_url = os.environ.get(ENV_DATABASE_URL, "").strip()
    if env_url and is_sqlite(env_url):
        return sqlite_path_from_url(env_url)
    raw = os.environ.get("APP_SQLITE_PATH", "").strip()
    return resolve_sqlite_file_path(raw or None)


def get_conn(db_path: Path | str | None = None) -> ConnectionLike:
    """DB 커넥션을 반환한다.

    Phase 3.2 부터 PostgreSQL 도 지원한다 — DBConnection wrapper 가
    sqlite3.Connection 인터페이스 (`execute("... ?", (1,))`, `row["col"]`,
    `commit`, `executescript`, ...) 를 그대로 제공하므로 호출부 변경 없음.

    - 인자 없거나 sqlite://URL → 기존 sqlite3.Connection 반환 (가장 가벼움)
    - Path / str 경로 → sqlite 파일에 sqlite3.Connection 직결
    - DATABASE_URL=postgresql://... → DBConnection wrapper 반환
    """
    if db_path is None:
        resolved = resolve_database_url()
        if is_sqlite(resolved):
            return make_sqlite_connection(resolved)
        return make_db_connection(resolved)
    if isinstance(db_path, str) and "://" in db_path:
        if is_sqlite(db_path):
            return make_sqlite_connection(db_path)
        return make_db_connection(db_path)
    path = resolve_sqlite_file_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# `INSERT OR REPLACE` 는 SQLite 전용. PG 호환을 위해 ON CONFLICT 로 통일.
_INSERT_JOB_RESULT_SQL = (
    "INSERT INTO job_results(job_id, report_json_path, partial_jsonl_path, summary_json) "
    "VALUES(?, ?, ?, ?) "
    "ON CONFLICT(job_id) DO UPDATE SET "
    "  report_json_path=excluded.report_json_path, "
    "  partial_jsonl_path=excluded.partial_jsonl_path, "
    "  summary_json=excluded.summary_json"
)


def _is_sqlite_conn(conn: ConnectionLike) -> bool:
    """주어진 커넥션이 SQLite 위에서 동작 중인지 판정."""
    if isinstance(conn, sqlite3.Connection):
        return True
    if isinstance(conn, DBConnection):
        return conn.dialect == "sqlite"
    return True


def init_db(conn: ConnectionLike) -> None:
    """스키마 초기화 — dialect 별 자동 증가 컬럼 표현 차이만 분기.

    - SQLite : ``INTEGER PRIMARY KEY AUTOINCREMENT``
    - Postgres: ``BIGSERIAL PRIMARY KEY`` (PG 10+ 의 IDENTITY 대신 호환성 우선)
    """
    autoinc = "INTEGER PRIMARY KEY AUTOINCREMENT" if _is_sqlite_conn(conn) else "BIGSERIAL PRIMARY KEY"
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS jobs (
            id {autoinc},
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS job_results (
            id {autoinc},
            job_id INTEGER NOT NULL UNIQUE,
            report_json_path TEXT NOT NULL,
            partial_jsonl_path TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id {autoinc},
            job_id INTEGER,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS job_tasks (
            id {autoinc},
            job_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempt INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_job_tasks_job_status ON job_tasks(job_id, status);
        CREATE INDEX IF NOT EXISTS idx_job_tasks_status ON job_tasks(status, id);
        """
    )
    _migrate_add_token_columns(conn)
    conn.commit()


def _existing_columns(conn: ConnectionLike, table: str) -> set:
    """테이블의 컬럼 이름 집합을 반환 — dialect-agnostic.

    SQLite 는 PRAGMA, Postgres 는 information_schema 를 직접 조회한다.
    SA inspector 를 사용하지 않는 이유: 동일 트랜잭션 안에서 방금 CREATE 한
    테이블을 inspector 가 못 보는 경우가 있다 (PG DDL 가시성).
    """
    if isinstance(conn, DBConnection) and conn.dialect == "postgresql":
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_schema = current_schema()",
            (table,),
        )
        return {str(row[0]) for row in cur.fetchall()}
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cur.fetchall()}


def _migrate_add_token_columns(conn: ConnectionLike) -> None:
    """기존 DB에 토큰 사용량 컬럼이 없을 경우 추가 (멱등, dialect-agnostic)."""
    existing = _existing_columns(conn, "job_tasks")
    for col in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if col not in existing:
            conn.execute(f"ALTER TABLE job_tasks ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")


def enqueue_job(conn: ConnectionLike, title: str, payload: dict[str, Any], *, status: str = "pending") -> int:
    cur = conn.execute(
        "INSERT INTO jobs(status, title, payload_json) VALUES(?, ?, ?) RETURNING id",
        (status, title, json.dumps(payload, ensure_ascii=False)),
    )
    new_id = _fetch_inserted_id(cur)
    conn.commit()
    return new_id


def update_job_payload(conn: ConnectionLike, job_id: int, payload: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE jobs SET payload_json=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), job_id),
    )
    conn.commit()


def fetch_jobs(conn: ConnectionLike, limit: int = 100) -> list[Any]:
    cur = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return cur.fetchall()


def _jobs_list_filters(status: str | None, q: str | None) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("j.status = ?")
        params.append(status)
    if q and q.strip():
        qst = q.strip()
        if qst.isdigit():
            clauses.append("(j.title LIKE ? OR j.id = ?)")
            params.extend([f"%{qst}%", int(qst)])
        else:
            clauses.append("j.title LIKE ?")
            params.append(f"%{qst}%")
    return clauses, params


def count_jobs(conn: ConnectionLike, status: str | None = None, q: str | None = None) -> int:
    clauses, params = _jobs_list_filters(status, q)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = conn.execute(f"SELECT COUNT(*) AS c FROM jobs j{where}", params)
    row = cur.fetchone()
    return int(row["c"]) if row is not None else 0


def fetch_jobs_extended(
    conn: ConnectionLike,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
    include_payload: bool = False,
) -> list[Any]:
    """작업 목록 + job_results.summary_json (있으면)."""
    clauses, params = _jobs_list_filters(status, q)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    base_cols = "j.id, j.status, j.title, j.created_at, j.started_at, j.finished_at, j.error_message"
    if include_payload:
        base_cols += ", j.payload_json"
    sql = f"""
        SELECT {base_cols}, jr.summary_json AS summary_json
        FROM jobs j
        LEFT JOIN job_results jr ON jr.job_id = j.id
        {where}
        ORDER BY j.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    cur = conn.execute(sql, params)
    return cur.fetchall()


def fetch_job_with_result(conn: ConnectionLike, job_id: int) -> Any | None:
    cur = conn.execute(
        """
        SELECT j.*, jr.summary_json AS summary_json,
               jr.report_json_path AS report_json_path,
               jr.partial_jsonl_path AS result_partial_jsonl_path
        FROM jobs j
        LEFT JOIN job_results jr ON jr.job_id = j.id
        WHERE j.id = ?
        """,
        (job_id,),
    )
    return cur.fetchone()


def queue_status_counts(conn: ConnectionLike) -> dict[str, int]:
    cur = conn.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status")
    out: dict[str, int] = {}
    for row in cur.fetchall():
        out[str(row["status"])] = int(row["c"])
    return out


def _begin_immediate(conn: ConnectionLike) -> None:
    """SQLite 에서는 BEGIN IMMEDIATE, 그 외에는 BEGIN — 큐 선점 시 동시성 보호."""
    dialect = "sqlite"
    if isinstance(conn, DBConnection):
        dialect = conn.dialect
    if dialect == "sqlite":
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute("BEGIN")


def claim_next_pending_job(conn: ConnectionLike) -> Any | None:
    cur = conn.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY id ASC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return None
    updated = conn.execute(
        """
        UPDATE jobs
        SET status='running', started_at=CURRENT_TIMESTAMP
        WHERE id=? AND status='pending'
        """,
        (int(row["id"]),),
    )
    conn.commit()
    if updated.rowcount == 0:
        return None
    cur2 = conn.execute("SELECT * FROM jobs WHERE id=?", (int(row["id"]),))
    return cur2.fetchone()


def complete_job(
    conn: ConnectionLike,
    job_id: int,
    report_json_path: str,
    partial_jsonl_path: str,
    summary: dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET status='completed', finished_at=CURRENT_TIMESTAMP, error_message=NULL
        WHERE id=?
        """,
        (job_id,),
    )
    conn.execute(
        _INSERT_JOB_RESULT_SQL,
        (
            job_id,
            report_json_path,
            partial_jsonl_path,
            json.dumps(summary, ensure_ascii=False),
        ),
    )
    conn.commit()


def fail_job(conn: ConnectionLike, job_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET status='failed', finished_at=CURRENT_TIMESTAMP, error_message=?
        WHERE id=?
        """,
        (error_message, job_id),
    )
    conn.commit()


def add_notification(conn: ConnectionLike, job_id: int | None, n_type: str, title: str, message: str) -> None:
    conn.execute(
        "INSERT INTO notifications(job_id, type, title, message) VALUES(?, ?, ?, ?)",
        (job_id, n_type, title, message),
    )
    conn.commit()


def fetch_notifications(conn: ConnectionLike, limit: int = 50) -> list[Any]:
    cur = conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
    return cur.fetchall()


def unread_notification_count(conn: ConnectionLike) -> int:
    cur = conn.execute("SELECT COUNT(*) AS c FROM notifications WHERE is_read=0")
    return int(cur.fetchone()["c"])


def mark_notification_read(conn: ConnectionLike, notification_id: int) -> None:
    conn.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notification_id,))
    conn.commit()


def fetch_job_result(conn: ConnectionLike, job_id: int) -> Any | None:
    cur = conn.execute("SELECT * FROM job_results WHERE job_id=?", (job_id,))
    return cur.fetchone()


def fetch_job_basic(conn: ConnectionLike, job_id: int) -> Any | None:
    """ID/제목/payload_json 만 가벼이 조회 (이미지 등 payload 필드 접근용)."""
    cur = conn.execute(
        "SELECT id, title, payload_json FROM jobs WHERE id=?",
        (job_id,),
    )
    return cur.fetchone()


def fetch_job(conn: ConnectionLike, job_id: int) -> Any | None:
    """단일 job 행 전체 조회. status/payload_json/started_at 등 모든 컬럼 포함."""
    cur = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    return cur.fetchone()


_DELETABLE_JOB_STATUSES = frozenset({"failed", "completed"})


def delete_job(conn: ConnectionLike, job_id: int) -> None:
    """완료·실패 작업과 연관 행을 DB에서 제거합니다. 출력 디렉터리는 호출측에서 정리."""
    job = fetch_job(conn, job_id)
    if job is None:
        raise ValueError("job not found")
    status = str(job["status"])
    if status not in _DELETABLE_JOB_STATUSES:
        raise ValueError("완료 또는 실패 상태의 작업만 삭제할 수 있습니다")

    conn.execute("DELETE FROM job_tasks WHERE job_id=?", (job_id,))
    conn.execute("DELETE FROM job_results WHERE job_id=?", (job_id,))
    conn.execute("DELETE FROM notifications WHERE job_id=?", (job_id,))
    cur = conn.execute(
        "DELETE FROM jobs WHERE id=? AND status IN ('failed', 'completed')",
        (job_id,),
    )
    if int(cur.rowcount or 0) == 0:
        raise ValueError("삭제에 실패했습니다")
    conn.commit()


def transition_job_status(
    conn: ConnectionLike,
    job_id: int,
    *,
    from_status: str,
    to_status: str,
) -> bool:
    """조건부 상태 전이 (예: preparing→pending). 성공 시 True."""
    cur = conn.execute(
        "UPDATE jobs SET status=? WHERE id=? AND status=?",
        (to_status, job_id, from_status),
    )
    conn.commit()
    return int(cur.rowcount or 0) > 0


def start_job_running(conn: ConnectionLike, job_id: int) -> None:
    """job 을 running 으로 표시하고 started_at 을 (없을 때만) 기록.

    완료/실패 상태인 job 도 status 만 다시 running 으로 덮어쓰지 않도록 호출자가
    상태를 사전 확인해야 한다 — 본 함수는 단순 UPDATE 만 수행한다.
    """
    conn.execute(
        "UPDATE jobs SET status='running', started_at=COALESCE(started_at, CURRENT_TIMESTAMP) WHERE id=?",
        (job_id,),
    )
    conn.commit()


def insert_job_task(
    conn: ConnectionLike,
    job_id: int,
    task_type: str,
    payload: dict[str, Any],
) -> int:
    cur = conn.execute(
        "INSERT INTO job_tasks(job_id, task_type, payload_json, status) VALUES(?, ?, ?, 'pending') RETURNING id",
        (job_id, task_type, json.dumps(payload, ensure_ascii=False)),
    )
    new_id = _fetch_inserted_id(cur)
    conn.commit()
    return new_id


def claim_next_pending_task(conn: ConnectionLike) -> Any | None:
    """LLM 세분화 큐: pending 태스크 1건을 running으로 선점."""
    _begin_immediate(conn)
    cur = conn.execute(
        "SELECT * FROM job_tasks WHERE status='pending' ORDER BY id ASC LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        conn.commit()
        return None
    tid = int(row["id"])
    updated = conn.execute(
        """
        UPDATE job_tasks
        SET status='running', started_at=CURRENT_TIMESTAMP, attempt=attempt+1
        WHERE id=? AND status='pending'
        """,
        (tid,),
    )
    conn.commit()
    if updated.rowcount == 0:
        return None
    cur2 = conn.execute("SELECT * FROM job_tasks WHERE id=?", (tid,))
    return cur2.fetchone()


def complete_task(
    conn: ConnectionLike,
    task_id: int,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    """태스크 완료 표시. 토큰 사용량은 함께 누적 저장됩니다(재시도 시에도 덮어쓰기)."""
    conn.execute(
        """
        UPDATE job_tasks
        SET status='completed',
            finished_at=CURRENT_TIMESTAMP,
            error_message=NULL,
            prompt_tokens=?,
            completion_tokens=?,
            total_tokens=?
        WHERE id=?
        """,
        (int(prompt_tokens or 0), int(completion_tokens or 0), int(total_tokens or 0), task_id),
    )
    conn.commit()


def job_token_totals(conn: ConnectionLike, job_id: int) -> dict[str, int]:
    """job 단위 토큰 사용량 합계.

    완료된 태스크뿐 아니라 모든 task 행을 합산해 부분 실행 비용도 반영합니다.
    """
    cur = conn.execute(
        """
        SELECT
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COUNT(*) AS task_count
        FROM job_tasks
        WHERE job_id=?
        """,
        (job_id,),
    )
    row = cur.fetchone()
    if row is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "task_count": 0}
    return {
        "prompt_tokens": int(row["prompt_tokens"]),
        "completion_tokens": int(row["completion_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "task_count": int(row["task_count"]),
    }


def fail_task(conn: ConnectionLike, task_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE job_tasks
        SET status='failed', finished_at=CURRENT_TIMESTAMP, error_message=?
        WHERE id=?
        """,
        (error_message, task_id),
    )
    conn.commit()


def reset_task_pending(conn: ConnectionLike, task_id: int) -> None:
    conn.execute(
        "UPDATE job_tasks SET status='pending', started_at=NULL, error_message=NULL WHERE id=?",
        (task_id,),
    )
    conn.commit()


def count_job_tasks(conn: ConnectionLike, job_id: int, status: str | None = None) -> int:
    if status:
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM job_tasks WHERE job_id=? AND status=?",
            (job_id, status),
        )
    else:
        cur = conn.execute("SELECT COUNT(*) AS c FROM job_tasks WHERE job_id=?", (job_id,))
    return int(cur.fetchone()["c"])


def latest_failed_task_error(conn: ConnectionLike, job_id: int) -> str | None:
    """job 의 가장 최근 실패한 태스크의 error_message 를 반환합니다(없으면 None)."""
    cur = conn.execute(
        """
        SELECT error_message
        FROM job_tasks
        WHERE job_id=? AND status='failed' AND error_message IS NOT NULL
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC, id DESC
        LIMIT 1
        """,
        (job_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    msg = row["error_message"]
    return str(msg) if msg is not None else None


def job_task_status_counts(conn: ConnectionLike, job_id: int) -> dict[str, int]:
    """job_id 기준 페르소나 LLM 태스크 상태별 건수(진행률·ETA용)."""
    cur = conn.execute(
        """
        SELECT status, COUNT(*) AS c
        FROM job_tasks
        WHERE job_id=?
        GROUP BY status
        """,
        (job_id,),
    )
    out = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for row in cur.fetchall():
        key = str(row["status"])
        if key in out:
            out[key] = int(row["c"])
    out["total"] = sum(out[k] for k in ("pending", "running", "completed", "failed"))
    return out


def job_has_tasks(conn: ConnectionLike, job_id: int) -> bool:
    return count_job_tasks(conn, job_id) > 0


def claim_next_pending_job_legacy_only(conn: ConnectionLike) -> Any | None:
    """job_tasks가 없는 pending job만 (기존 서브프로세스 경로)."""
    cur = conn.execute(
        """
        SELECT j.* FROM jobs j
        WHERE j.status='pending'
        AND NOT EXISTS (SELECT 1 FROM job_tasks t WHERE t.job_id = j.id)
        ORDER BY j.id ASC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        return None
    updated = conn.execute(
        """
        UPDATE jobs
        SET status='running', started_at=CURRENT_TIMESTAMP
        WHERE id=? AND status='pending'
        """,
        (int(row["id"]),),
    )
    conn.commit()
    if updated.rowcount == 0:
        return None
    cur2 = conn.execute("SELECT * FROM jobs WHERE id=?", (int(row["id"]),))
    return cur2.fetchone()
