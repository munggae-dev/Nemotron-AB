"""V7-c: 실제 Ollama 호출 end-to-end + 토큰 적재·집계.

`LLM_BASE_URL` (기본 http://localhost:11434/v1) 와 `LLM_MODEL` 환경변수로 대상 지정.
페르소나 풀과 Ollama 가 모두 갖춰진 환경에서만 실행된다.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Tuple

import pytest

from tests.integration.conftest import DEFAULT_OLLAMA_BASE, DEFAULT_OLLAMA_MODEL


pytestmark = [
    pytest.mark.integration,
    pytest.mark.needs_persona_db,
    pytest.mark.needs_ollama,
]


def _post_json(url: str, body: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _wait_terminal(base_url: str, job_id: int, *, timeout_sec: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    last: dict = {}
    while time.monotonic() < deadline:
        last = _get_json(f"{base_url}/jobs/{job_id}")
        if last.get("status") in ("completed", "failed"):
            return last
        time.sleep(3)
    pytest.fail(f"job {job_id} did not finish in {timeout_sec}s. last={last}")


def test_llm_job_records_tokens(
    stack: Tuple[str, Path],
    persona_db_required,
    ollama_required: str,
) -> None:
    base_url, _db = stack
    body = {
        "title": "E2E LLM token test",
        "text_a": "오늘 가입하고 10% 할인 받기",
        "text_b": "내일 가입해도 같은 혜택",
        "context": "회원 가입 권유 문구 A/B",
        "evaluator": "langchain",
        "profile": "small",
        "max_personas": 8,
        "retrieval_k_per_bucket": 20,
        "eval_concurrency": 2,
        "seed": 42,
        "max_reason_chars": 60,
        "use_llm_task_queue": True,
        "llm_base_url": ollama_required,
        "llm_model": DEFAULT_OLLAMA_MODEL,
        "response_format_json": True,
        "persona_filter": {
            "sex": "all",
            "age_min": 20,
            "age_max": 50,
            "province": "",
            "district": "",
        },
    }
    created = _post_json(f"{base_url}/jobs", body)
    job_id = int(created["id"])
    final = _wait_terminal(base_url, job_id, timeout_sec=600.0)
    assert final["status"] == "completed", final

    tokens = final["tokens"]
    assert tokens["task_count"] == 8
    assert tokens["prompt_tokens"] > 0, "prompt_tokens 가 적재되지 않았습니다"
    assert tokens["completion_tokens"] > 0, "completion_tokens 가 적재되지 않았습니다"
    # 합산 항등식: prompt + completion == total (모델이 동일 항등 보고 시)
    assert tokens["total_tokens"] == tokens["prompt_tokens"] + tokens["completion_tokens"]

    # report_summary 안에 토큰 사본도 포함되어 있어야 한다
    summary = final["report_summary"]
    assert "tokens" in summary
    assert summary["tokens"]["total_tokens"] == tokens["total_tokens"]
