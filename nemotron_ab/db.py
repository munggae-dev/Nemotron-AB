import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


def default_sqlite_path() -> Path:
    """환경변수 APP_SQLITE_PATH 또는 저장소 기본 app/app.sqlite3."""
    import os

    raw = os.environ.get("APP_SQLITE_PATH", "").strip()
    repo_root = Path(__file__).resolve().parents[1]
    return Path(raw) if raw else repo_root / "nemotron_ab" / "app.sqlite3"


def get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS job_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL UNIQUE,
            report_json_path TEXT NOT NULL,
            partial_jsonl_path TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );

        CREATE TABLE IF NOT EXISTS job_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempt INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
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


def _migrate_add_token_columns(conn: sqlite3.Connection) -> None:
    """기존 DB에 토큰 사용량 컬럼이 없을 경우 추가 (멱등)."""
    cur = conn.execute("PRAGMA table_info(job_tasks)")
    existing = {str(row[1]) for row in cur.fetchall()}
    for col in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if col not in existing:
            conn.execute(f"ALTER TABLE job_tasks ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")


def enqueue_job(conn: sqlite3.Connection, title: str, payload: Dict[str, Any], *, status: str = "pending") -> int:
    cur = conn.execute(
        "INSERT INTO jobs(status, title, payload_json) VALUES(?, ?, ?)",
        (status, title, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_job_payload(conn: sqlite3.Connection, job_id: int, payload: Dict[str, Any]) -> None:
    conn.execute(
        "UPDATE jobs SET payload_json=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), job_id),
    )
    conn.commit()


def fetch_jobs(conn: sqlite3.Connection, limit: int = 100) -> List[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return cur.fetchall()


def fetch_jobs_extended(
    conn: sqlite3.Connection,
    limit: int = 100,
    status: Optional[str] = None,
    q: Optional[str] = None,
    include_payload: bool = False,
) -> List[sqlite3.Row]:
    """작업 목록 + job_results.summary_json (있으면)."""
    clauses: List[str] = []
    params: List[Any] = []
    if status:
        clauses.append("j.status = ?")
        params.append(status)
    if q and q.strip():
        clauses.append("j.title LIKE ?")
        params.append(f"%{q.strip()}%")
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
        LIMIT ?
    """
    params.append(limit)
    cur = conn.execute(sql, params)
    return cur.fetchall()


def fetch_job_with_result(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
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


def queue_status_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    cur = conn.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status")
    out: Dict[str, int] = {}
    for row in cur.fetchall():
        out[str(row["status"])] = int(row["c"])
    return out


def claim_next_pending_job(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY id ASC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return None
    updated = conn.execute(
        """
        UPDATE jobs
        SET status='running', started_at=datetime('now')
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
    conn: sqlite3.Connection,
    job_id: int,
    report_json_path: str,
    partial_jsonl_path: str,
    summary: Dict[str, Any],
) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET status='completed', finished_at=datetime('now'), error_message=NULL
        WHERE id=?
        """,
        (job_id,),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO job_results(job_id, report_json_path, partial_jsonl_path, summary_json)
        VALUES(?, ?, ?, ?)
        """,
        (
            job_id,
            report_json_path,
            partial_jsonl_path,
            json.dumps(summary, ensure_ascii=False),
        ),
    )
    conn.commit()


def fail_job(conn: sqlite3.Connection, job_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET status='failed', finished_at=datetime('now'), error_message=?
        WHERE id=?
        """,
        (error_message, job_id),
    )
    conn.commit()


def add_notification(conn: sqlite3.Connection, job_id: Optional[int], n_type: str, title: str, message: str) -> None:
    conn.execute(
        "INSERT INTO notifications(job_id, type, title, message) VALUES(?, ?, ?, ?)",
        (job_id, n_type, title, message),
    )
    conn.commit()


def fetch_notifications(conn: sqlite3.Connection, limit: int = 50) -> List[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
    return cur.fetchall()


def unread_notification_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) AS c FROM notifications WHERE is_read=0")
    return int(cur.fetchone()["c"])


def mark_notification_read(conn: sqlite3.Connection, notification_id: int) -> None:
    conn.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notification_id,))
    conn.commit()


def fetch_job_result(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM job_results WHERE job_id=?", (job_id,))
    return cur.fetchone()


def insert_job_task(
    conn: sqlite3.Connection,
    job_id: int,
    task_type: str,
    payload: Dict[str, Any],
) -> int:
    cur = conn.execute(
        "INSERT INTO job_tasks(job_id, task_type, payload_json, status) VALUES(?, ?, ?, 'pending')",
        (job_id, task_type, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    return int(cur.lastrowid)


def claim_next_pending_task(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """LLM 세분화 큐: pending 태스크 1건을 running으로 선점."""
    conn.execute("BEGIN IMMEDIATE")
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
        SET status='running', started_at=datetime('now'), attempt=attempt+1
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
    conn: sqlite3.Connection,
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
            finished_at=datetime('now'),
            error_message=NULL,
            prompt_tokens=?,
            completion_tokens=?,
            total_tokens=?
        WHERE id=?
        """,
        (int(prompt_tokens or 0), int(completion_tokens or 0), int(total_tokens or 0), task_id),
    )
    conn.commit()


def job_token_totals(conn: sqlite3.Connection, job_id: int) -> Dict[str, int]:
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


def fail_task(conn: sqlite3.Connection, task_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE job_tasks
        SET status='failed', finished_at=datetime('now'), error_message=?
        WHERE id=?
        """,
        (error_message, task_id),
    )
    conn.commit()


def reset_task_pending(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute(
        "UPDATE job_tasks SET status='pending', started_at=NULL, error_message=NULL WHERE id=?",
        (task_id,),
    )
    conn.commit()


def count_job_tasks(conn: sqlite3.Connection, job_id: int, status: Optional[str] = None) -> int:
    if status:
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM job_tasks WHERE job_id=? AND status=?",
            (job_id, status),
        )
    else:
        cur = conn.execute("SELECT COUNT(*) AS c FROM job_tasks WHERE job_id=?", (job_id,))
    return int(cur.fetchone()["c"])


def job_task_status_counts(conn: sqlite3.Connection, job_id: int) -> Dict[str, int]:
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


def job_has_tasks(conn: sqlite3.Connection, job_id: int) -> bool:
    return count_job_tasks(conn, job_id) > 0


def claim_next_pending_job_legacy_only(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
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
        SET status='running', started_at=datetime('now')
        WHERE id=? AND status='pending'
        """,
        (int(row["id"]),),
    )
    conn.commit()
    if updated.rowcount == 0:
        return None
    cur2 = conn.execute("SELECT * FROM jobs WHERE id=?", (int(row["id"]),))
    return cur2.fetchone()
