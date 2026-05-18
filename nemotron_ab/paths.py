"""저장소 루트 기준 경로 해석 (cwd 독립).

API(uvicorn)를 `backend/` 에서 띄우고 워커를 프로젝트 루트에서 띄워도
`APP_SQLITE_PATH=./nemotron_ab/app.sqlite3` 처럼 상대 경로가 동일한 DB를 가리키도록 한다.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_SQLITE_REL = Path("nemotron_ab") / "app.sqlite3"


def repo_root() -> Path:
    """패키지 `nemotron_ab/` 의 부모 = Git 저장소 루트."""
    return Path(__file__).resolve().parents[1]


def resolve_sqlite_file_path(raw: str | Path | None = None) -> Path:
    """SQLite 파일 경로를 저장소 루트 기준 절대 경로로 정규화한다.

    - 미설정/빈 문자열 → ``{repo}/nemotron_ab/app.sqlite3``
    - 상대 경로 → ``repo_root / raw`` (실행 cwd 무관)
    - 절대 경로 → 그대로 ``resolve()``
    """
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return (repo_root() / DEFAULT_SQLITE_REL).resolve()
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root() / path
    return path.resolve()
