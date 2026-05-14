"""SQLAlchemy 엔진/URL 해석 헬퍼.

Phase 3 의 첫 단계로, DB 접속 정보를 단일 진입점으로 모은다.

설정 우선순위:

1. 함수 인자 `url`
2. 환경변수 `DATABASE_URL` (예: `postgresql+psycopg://user:pw@host/db`)
3. `APP_SQLITE_PATH` → `sqlite:///{path}` 로 자동 변환
4. 저장소 기본 경로 (`nemotron_ab/app.sqlite3`)

Phase 3.1 현재는 SQLite 만 정식 지원하며, 비-SQLite URL 은 `make_engine` 에서
정상 동작하지만 `get_conn` 호환 wrapper 는 SQLite 만 반환합니다.
Postgres 본격 지원은 Phase 3.2 에서 db.py 의 SQL 을 SA Core 로 재작성하며
이뤄집니다.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import Engine, create_engine, event


ENV_DATABASE_URL = "DATABASE_URL"


def _default_sqlite_path_from_app() -> Path:
    """db.py 의 default_sqlite_path 와 동일한 규칙 — 순환 import 회피용 자체 구현.

    APP_SQLITE_PATH 환경변수 우선, 미지정 시 저장소 기본 위치.
    """
    raw = os.environ.get("APP_SQLITE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "nemotron_ab" / "app.sqlite3"


def resolve_database_url(url: Optional[str] = None) -> str:
    """최종 DB URL 을 결정한다."""
    if url:
        return url.strip()
    env = os.environ.get(ENV_DATABASE_URL, "").strip()
    if env:
        return env
    return f"sqlite:///{_default_sqlite_path_from_app()}"


def dialect_name(url: str) -> str:
    """URL 스키마에서 방언 이름을 추출. 예: 'sqlite', 'postgresql', 'postgres'."""
    scheme = urlparse(url).scheme or ""
    base = scheme.split("+", 1)[0].lower()
    if base == "postgres":
        return "postgresql"
    return base


def is_sqlite(url: str) -> bool:
    return dialect_name(url) == "sqlite"


def is_postgres(url: str) -> bool:
    return dialect_name(url) == "postgresql"


def sqlite_path_from_url(url: str) -> Path:
    """`sqlite:///abs/path.db` → Path 변환.

    `sqlite:///:memory:` 도 그대로 받지만, 호출자는 in-memory 가 다중 커넥션 간
    공유되지 않는다는 SQLite 의 특성을 인지해야 한다.
    """
    if not is_sqlite(url):
        raise ValueError(f"sqlite URL 이 아닙니다: {url!r}")
    raw = url[len("sqlite:///") :] if url.startswith("sqlite:///") else url[len("sqlite://") :]
    return Path(raw)


def make_engine(url: Optional[str] = None, *, echo: bool = False) -> Engine:
    """SA Engine 을 만든다. SQLite 인 경우 외래키 PRAGMA 도 자동 켠다."""
    resolved = resolve_database_url(url)
    connect_args: dict = {}
    if is_sqlite(resolved):
        # FastAPI + 워커가 같은 sqlite 파일을 다중 스레드로 열기 때문에 필요
        connect_args["check_same_thread"] = False
    engine = create_engine(resolved, echo=echo, future=True, connect_args=connect_args)
    if is_sqlite(resolved):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_conn, _record):  # noqa: ANN001
            try:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
            except Exception:  # noqa: BLE001
                pass
    return engine


def make_sqlite_connection(url: Optional[str] = None) -> sqlite3.Connection:
    """SQLite 전용 DBAPI 커넥션을 직접 만든다.

    Phase 3.1 의 호환 경로: db.py 의 기존 코드가 sqlite3.Connection 인터페이스를
    그대로 사용하므로, SA Engine 을 통하지 않고 DBAPI 를 바로 연결한다.
    Phase 3.2 에서 db.py 가 SA Core 로 옮겨가면 이 함수는 점진적으로 폐기된다.
    """
    resolved = resolve_database_url(url)
    if not is_sqlite(resolved):
        raise NotImplementedError(
            "Phase 3.1 에서는 DATABASE_URL 이 sqlite:/// 인 경우만 지원합니다. "
            f"입력: {resolved!r}. Postgres 지원은 Phase 3.2 에서 활성화됩니다."
        )
    path = sqlite_path_from_url(resolved)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
