import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


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
        """
    )
    conn.commit()


def enqueue_job(conn: sqlite3.Connection, title: str, payload: Dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO jobs(status, title, payload_json) VALUES('pending', ?, ?)",
        (title, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    return int(cur.lastrowid)


def fetch_jobs(conn: sqlite3.Connection, limit: int = 100) -> List[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return cur.fetchall()


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
