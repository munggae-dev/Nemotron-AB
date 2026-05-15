"""FastAPI 공통 의존성 (DB 연결 등)."""
from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nemotron_ab import db


def db_path() -> Path:
    return db.default_sqlite_path()


@contextmanager
def get_conn() -> Generator:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_conn(path)
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()
