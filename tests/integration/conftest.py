"""통합 테스트용 픽스처/유틸.

외부 의존(uvicorn, worker, ChromaDB persona_db, Ollama)이 필요한 케이스에서
환경이 갖춰지지 않았으면 자동으로 skip 한다.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Iterator, Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OLLAMA_BASE = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.environ.get("LLM_MODEL", "gemma4:e2b-it-q4_K_M")


def _pick_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http_ok(url: str, *, timeout_sec: float = 20.0, interval: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(interval)
    return False


def _ollama_available(base_url: str = DEFAULT_OLLAMA_BASE) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=2) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def _persona_db_built() -> bool:
    return (REPO_ROOT / "persona_db").exists() and any(
        (REPO_ROOT / "persona_db").iterdir()
    )


@pytest.fixture(scope="module")
def persona_db_required() -> None:
    if not _persona_db_built():
        pytest.skip("persona_db 가 없습니다. scripts/build_vectordb.py 로 먼저 빌드하세요.")


@pytest.fixture(scope="module")
def ollama_required() -> str:
    if not _ollama_available():
        pytest.skip(f"Ollama({DEFAULT_OLLAMA_BASE}) 응답 없음. ollama serve 후 다시 실행하세요.")
    return DEFAULT_OLLAMA_BASE


@pytest.fixture()
def stack(tmp_path: Path) -> Iterator[Tuple[str, Path]]:
    """uvicorn + worker 를 격리 SQLite 위에서 띄운다. (base_url, db_path) 를 반환."""
    db_path = tmp_path / "app.sqlite3"
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["APP_SQLITE_PATH"] = str(db_path)
    env["OUTPUT_BASE"] = str(out_dir)
    env["PYTHONUNBUFFERED"] = "1"

    port = _pick_free_port()
    api_log = tmp_path / "api.log"
    worker_log = tmp_path / "worker.log"

    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=api_log.open("w"),
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(REPO_ROOT),
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        if not _wait_http_ok(f"{base_url}/health", timeout_sec=30.0):
            pytest.fail(f"uvicorn 시작 실패. log: {api_log.read_text()[-2000:]}")

        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "nemotron_ab.worker_main",
                "--db-path",
                str(db_path),
                "--poll-interval-sec",
                "1",
                "--max-jobs-per-tick",
                "1",
                "--task-parallelism",
                "2",
            ],
            stdout=worker_log.open("w"),
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(REPO_ROOT),
        )

        try:
            yield base_url, db_path
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
