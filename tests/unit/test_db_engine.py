"""Phase 3.1: db_engine URL 해석 + 환경변수 우선순위 + sqlite 연결 검증.

Postgres 본격 지원은 Phase 3.2 에서 (postgres URL 은 NotImplementedError 검증만).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def test_resolve_database_url_default_uses_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nemotron_ab.db_engine import resolve_database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_SQLITE_PATH", str(tmp_path / "x.sqlite3"))
    url = resolve_database_url()
    assert url.startswith("sqlite:///")
    assert str(tmp_path / "x.sqlite3") in url


def test_resolve_database_url_prefers_explicit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from nemotron_ab.db_engine import resolve_database_url

    monkeypatch.setenv("DATABASE_URL", "sqlite:///env-path.db")
    assert resolve_database_url("sqlite:///explicit.db") == "sqlite:///explicit.db"


def test_resolve_database_url_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from nemotron_ab.db_engine import resolve_database_url

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@host/db")
    assert resolve_database_url() == "postgresql+psycopg://user:pw@host/db"


def test_dialect_helpers() -> None:
    from nemotron_ab.db_engine import dialect_name, is_postgres, is_sqlite

    assert dialect_name("sqlite:///a.db") == "sqlite"
    assert is_sqlite("sqlite:///a.db")
    assert not is_postgres("sqlite:///a.db")
    assert is_postgres("postgresql+psycopg://u@h/d")
    assert is_postgres("postgres://u@h/d")  # 호환 스키마
    assert dialect_name("postgresql+psycopg://u@h/d") == "postgresql"


def test_sqlite_path_from_url(tmp_path: Path) -> None:
    from nemotron_ab.db_engine import sqlite_path_from_url

    p = sqlite_path_from_url(f"sqlite:///{tmp_path}/x.sqlite3")
    assert isinstance(p, Path)
    assert p == Path(f"{tmp_path}/x.sqlite3")


def test_sqlite_path_from_url_rejects_non_sqlite() -> None:
    from nemotron_ab.db_engine import sqlite_path_from_url

    with pytest.raises(ValueError):
        sqlite_path_from_url("postgresql://u@h/d")


def test_make_sqlite_connection_rejects_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    from nemotron_ab.db_engine import make_sqlite_connection

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u@h/d")
    with pytest.raises(NotImplementedError):
        make_sqlite_connection()


def test_make_engine_creates_sqlite_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sqlalchemy import Engine

    from nemotron_ab.db_engine import make_engine

    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = f"sqlite:///{tmp_path / 'eng.db'}"
    eng = make_engine(url)
    assert isinstance(eng, Engine)
    # 외래키 PRAGMA 가 켜져 있어야 한다
    with eng.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(text("PRAGMA foreign_keys")).fetchone()
        assert row is not None
        assert int(row[0]) == 1


def test_get_conn_default_honors_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`db.get_conn()` 을 인자 없이 호출하면 DATABASE_URL/APP_SQLITE_PATH 를 따른다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    target = tmp_path / "auto.sqlite3"
    monkeypatch.setenv("APP_SQLITE_PATH", str(target))

    from nemotron_ab import db

    conn = db.get_conn()
    try:
        db.init_db(conn)
    finally:
        conn.close()
    assert target.exists(), "APP_SQLITE_PATH 가 가리킨 파일에 init_db 가 적용되어야 한다"


def test_get_conn_accepts_sqlite_url_string(tmp_path: Path) -> None:
    from nemotron_ab import db

    target = tmp_path / "via-url.sqlite3"
    conn = db.get_conn(f"sqlite:///{target}")
    try:
        assert isinstance(conn, sqlite3.Connection)
        db.init_db(conn)
    finally:
        conn.close()
    assert target.exists()


def test_default_sqlite_path_prefers_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`DATABASE_URL=sqlite:///...` 일 때 default_sqlite_path 도 그 경로를 반환해야 한다."""
    target = tmp_path / "from-url.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target}")
    monkeypatch.setenv("APP_SQLITE_PATH", str(tmp_path / "ignored.sqlite3"))

    from nemotron_ab import db

    assert db.default_sqlite_path() == target
