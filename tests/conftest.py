"""tests/conftest.py — 공통 픽스처.

검증 시나리오에서 반복 사용한 도구를 픽스처로 정리합니다:
- 격리된 SQLite 경로 (APP_SQLITE_PATH 환경변수 자동 설정)
- 깨끗한 DB 커넥션 (init_db 까지 적용된)
- FakeChatOpenAI 팩토리 (langchain_openai 모듈을 인메모리로 교체해
  ChatOpenAI 응답·usage_metadata 를 자유롭게 주입)

실제 Ollama / persona_db 가 필요한 통합 테스트는 tests/integration/ 에서 별도
픽스처로 게이트합니다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def isolated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """APP_SQLITE_PATH 를 격리 경로로 고정한다. 절대 저장소 기본 DB 를 건드리지 않는다."""
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setenv("APP_SQLITE_PATH", str(db_path))
    return db_path


@pytest.fixture()
def fresh_conn(isolated_sqlite: Path):
    """init_db 까지 적용된 격리 SQLite 커넥션. 테스트 종료 시 자동 close."""
    from nemotron_ab import db

    conn = db.get_conn(isolated_sqlite)
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fake LLM helpers
# ---------------------------------------------------------------------------


class _FakeAIMsg:
    """LangChain AIMessage 호환 응답."""

    def __init__(
        self,
        content: str,
        usage_metadata: Optional[Dict[str, Any]] = None,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.content = content
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


def _eval_payload(metric_keys: List[str]) -> str:
    return json.dumps(
        {
            "winner": "A",
            "scores": {
                "A": {k: 80 for k in metric_keys},
                "B": {k: 60 for k in metric_keys},
            },
            "reason": "A 가 더 명확합니다",
        },
        ensure_ascii=False,
    )


@pytest.fixture()
def fake_chat_openai_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[..., type]:
    """`langchain_openai.ChatOpenAI` 를 가짜 구현으로 교체하는 팩토리.

    Returns:
        호출 시 `usage_metadata` / `response_metadata` / 응답 본문을 지정해
        가짜 ChatOpenAI 클래스를 주입하는 함수.
    """

    def _install(
        *,
        usage_metadata: Optional[Dict[str, Any]] = None,
        response_metadata: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        metric_keys: Optional[List[str]] = None,
    ) -> type:
        body = content or _eval_payload(metric_keys or ["interest", "trust", "click_intent", "purchase_intent"])

        class _FakeChatOpenAI:
            def __init__(self, **kwargs: Any) -> None:
                self.init_kwargs = kwargs

            def invoke(self, _messages: Any) -> _FakeAIMsg:
                return _FakeAIMsg(
                    content=body,
                    usage_metadata=usage_metadata,
                    response_metadata=response_metadata,
                )

        fake_mod = types.ModuleType("langchain_openai")
        fake_mod.ChatOpenAI = _FakeChatOpenAI  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "langchain_openai", fake_mod)

        # 이미 import 된 모듈은 재로드해 fresh ChatOpenAI 를 참조하도록 한다.
        for mod_name in ("nemotron_ab.llm_provider", "nemotron_ab.langchain_eval"):
            sys.modules.pop(mod_name, None)
        return _FakeChatOpenAI

    return _install
