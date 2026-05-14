"""SQLAlchemy 엔진/URL 해석 + sqlite3.Connection 호환 wrapper.

이 모듈은 두 가지 책임을 진다.

1. **URL 해석/Engine 팩토리** (`resolve_database_url`, `make_engine`).
2. **dialect-agnostic 커넥션 wrapper** (`DBConnection`).
   - sqlite3.Connection 과 거의 동일한 인터페이스 (`execute`, `executemany`,
     `executescript`, `commit`, `close`, `lastrowid`)
   - 결과 row 는 `RowWrapper` 로 wrap 되어 `row["col"]` / iter / `dict(row)` 호환
   - 내부적으로 SA Engine 의 raw_connection(DBAPI) 위에서 동작
   - `?` placeholder 는 PG 경로에선 자동으로 `%s` 로 치환
   - INSERT 의 `RETURNING id` 결과를 `lastrowid` 로 자동 노출 (PG 호환)

설정 우선순위:

1. 함수 인자 `url`
2. 환경변수 `DATABASE_URL`
3. `APP_SQLITE_PATH` → `sqlite:///{path}`
4. 저장소 기본 경로
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import Engine, create_engine, event

ENV_DATABASE_URL = "DATABASE_URL"


# ---------------------------------------------------------------------------
# URL / dialect 헬퍼
# ---------------------------------------------------------------------------


def _default_sqlite_path_from_app() -> Path:
    """db.py 의 default_sqlite_path 와 동일한 규칙 — 순환 import 회피용 자체 구현."""
    raw = os.environ.get("APP_SQLITE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "nemotron_ab" / "app.sqlite3"


def resolve_database_url(url: str | None = None) -> str:
    """최종 DB URL 을 결정한다."""
    if url:
        return url.strip()
    env = os.environ.get(ENV_DATABASE_URL, "").strip()
    if env:
        return env
    return f"sqlite:///{_default_sqlite_path_from_app()}"


def dialect_name(url: str) -> str:
    """URL 스키마에서 방언 이름을 추출. 예: 'sqlite', 'postgresql'."""
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
    """`sqlite:///abs/path.db` → Path 변환."""
    if not is_sqlite(url):
        raise ValueError(f"sqlite URL 이 아닙니다: {url!r}")
    raw = url[len("sqlite:///") :] if url.startswith("sqlite:///") else url[len("sqlite://") :]
    return Path(raw)


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """SA Engine 을 만든다. SQLite 인 경우 외래키 PRAGMA 도 자동 켠다."""
    resolved = resolve_database_url(url)
    connect_args: dict = {}
    if is_sqlite(resolved):
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


def make_sqlite_connection(url: str | None = None) -> sqlite3.Connection:
    """SQLite 전용 DBAPI 커넥션 (저수준)."""
    resolved = resolve_database_url(url)
    if not is_sqlite(resolved):
        raise NotImplementedError(
            "make_sqlite_connection 은 sqlite:/// URL 만 지원합니다. "
            f"입력: {resolved!r}. Postgres 는 make_engine 또는 DBConnection 을 사용하세요."
        )
    path = sqlite_path_from_url(resolved)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# sqlite3.Connection 호환 wrapper
# ---------------------------------------------------------------------------


class RowWrapper(Mapping[str, Any]):
    """sqlite3.Row 호환 row.

    지원: ``row[int]``, ``row["col"]``, ``iter(row)``, ``dict(row)``, ``len(row)``,
    ``row.keys()``. SA Row 와 sqlite3.Row 양쪽을 받아 통일된 인터페이스를 제공한다.
    """

    __slots__ = ("_values", "_keys", "_kmap")

    def __init__(self, values: Sequence[Any], keys: Sequence[str]) -> None:
        self._values = tuple(values)
        self._keys = tuple(keys)
        self._kmap = {k: i for i, k in enumerate(keys)}

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, int):
            return self._values[key]
        idx = self._kmap.get(str(key))
        if idx is None:
            raise KeyError(key)
        return self._values[idx]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self):  # type: ignore[override]
        return list(self._keys)


def _wrap_row(row: Any, columns: Sequence[str]) -> RowWrapper | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return RowWrapper(tuple(row), [d for d in row.keys()])
    if isinstance(row, RowWrapper):
        return row
    if hasattr(row, "_mapping"):
        m = row._mapping
        keys = list(m.keys())
        return RowWrapper([m[k] for k in keys], keys)
    return RowWrapper(tuple(row), list(columns))


# `?` placeholder 를 `%s` 로 치환. 문자열 리터럴('...') 안의 ? 는 보존한다.
_QMARK_RE = re.compile(r"\?")


def _translate_qmark(sql: str, target: str) -> str:
    """`?` → `%s` 변환 (PG 용). 문자열 리터럴 안의 ? 는 그대로 둔다."""
    if target == "qmark":
        return sql
    if target != "format":
        return sql
    out: list[str] = []
    i = 0
    in_squote = False
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            # SQL string literal toggle ('' 는 escape, 단순 토글로 충분)
            in_squote = not in_squote
            out.append(ch)
            i += 1
            continue
        if ch == "?" and not in_squote:
            out.append("%s")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_RETURNING_RE = re.compile(r"\bRETURNING\b", re.IGNORECASE)


class _CursorView:
    """execute 결과를 sqlite3.Cursor 비슷한 인터페이스로 노출.

    `rowcount`, `lastrowid`, `fetchone()`, `fetchall()`, iter 지원.
    """

    def __init__(self, dbapi_cursor: Any, *, lastrowid: int | None = None) -> None:
        self._cur = dbapi_cursor
        self._description_cache: list[str] | None = None
        self._lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        try:
            return int(self._cur.rowcount)
        except Exception:  # noqa: BLE001
            return -1

    @property
    def lastrowid(self) -> int | None:
        if self._lastrowid is not None:
            return self._lastrowid
        try:
            return int(self._cur.lastrowid) if self._cur.lastrowid is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _columns(self) -> list[str]:
        if self._description_cache is not None:
            return self._description_cache
        desc = getattr(self._cur, "description", None) or []
        cols = [d[0] for d in desc] if desc else []
        self._description_cache = cols
        return cols

    def fetchone(self) -> RowWrapper | None:
        try:
            row = self._cur.fetchone()
        except Exception:  # noqa: BLE001
            return None
        return _wrap_row(row, self._columns())

    def fetchall(self) -> list[RowWrapper]:
        try:
            rows = self._cur.fetchall()
        except Exception:  # noqa: BLE001
            return []
        cols = self._columns()
        return [r for r in (_wrap_row(row, cols) for row in rows) if r is not None]

    def __iter__(self):
        return iter(self.fetchall())


def _split_statements(script: str) -> list[str]:
    """간단한 SQL script 분할 — 세미콜론 기준, 문자열 리터럴 안의 ; 는 무시.

    PRAGMA / CREATE / INDEX 등 단순 DDL 만 다루므로 충분하다.
    """
    out: list[str] = []
    buf: list[str] = []
    in_squote = False
    for ch in script:
        if ch == "'":
            in_squote = not in_squote
            buf.append(ch)
            continue
        if ch == ";" and not in_squote:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


class DBConnection:
    """sqlite3.Connection 호환 wrapper. PG/SQLite 모두 지원.

    - 내부적으로 SA Engine 의 raw_connection (DBAPI) 위에서 동작.
    - 호출자는 기존 sqlite3 인터페이스 (`execute("... ?", (1,))`) 를 그대로 사용.
    - SQL 안의 `?` placeholder 는 PG 경로에선 자동 `%s` 로 변환.
    - INSERT 에 `RETURNING id` 가 있으면 첫 행을 `lastrowid` 로 자동 노출.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._dialect = engine.dialect.name
        self._raw = engine.raw_connection()
        # paramstyle: sqlite3=qmark, psycopg=format
        self._paramstyle = "qmark" if self._dialect == "sqlite" else "format"

    @property
    def dialect(self) -> str:
        return self._dialect

    @property
    def row_factory(self):  # noqa: D401
        """호환용 noop. wrapper 가 항상 RowWrapper 반환."""
        return None

    @row_factory.setter
    def row_factory(self, _value) -> None:
        # 호환을 위해 무시
        return None

    def _execute_one(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> _CursorView:
        if not isinstance(sql, str):
            raise TypeError(f"sql 은 str 이어야 합니다: {type(sql)!r}")
        translated = _translate_qmark(sql, self._paramstyle)
        cur = self._raw.cursor()
        if params is None:
            cur.execute(translated)
        else:
            cur.execute(translated, params)
        lastrowid: int | None = None
        if _RETURNING_RE.search(sql):
            try:
                first = cur.fetchone()
                if first is not None:
                    lastrowid = int(first[0])
            except Exception:  # noqa: BLE001
                lastrowid = None
        return _CursorView(cur, lastrowid=lastrowid)

    # --- sqlite3.Connection 호환 메서드 -----------------------------------

    def execute(self, sql: str, params=None) -> _CursorView:
        return self._execute_one(sql, params)

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> _CursorView:
        translated = _translate_qmark(sql, self._paramstyle)
        cur = self._raw.cursor()
        cur.executemany(translated, list(seq_of_params))
        return _CursorView(cur)

    def executescript(self, script: str) -> None:
        if self._dialect == "sqlite":
            # sqlite3.Connection.executescript 는 단일 호출로 multi-statement 처리
            self._raw.executescript(script)
            return
        cur = self._raw.cursor()
        for stmt in _split_statements(script):
            cur.execute(stmt)

    def commit(self) -> None:
        try:
            self._raw.commit()
        except Exception:  # noqa: BLE001
            pass

    def rollback(self) -> None:
        try:
            self._raw.rollback()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:  # noqa: BLE001
            pass

    # sqlite3.Connection 와 동일한 context manager 의미: 성공 시 commit, 실패 시 rollback.
    # __exit__ 에서 닫지 않음 (sqlite3 동작 호환).
    def __enter__(self) -> DBConnection:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


def make_db_connection(url: str | None = None) -> DBConnection:
    """`DBConnection` 인스턴스 생성 헬퍼."""
    engine = make_engine(url)
    return DBConnection(engine)
