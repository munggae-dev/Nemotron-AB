"""V7-a: uvicorn + worker + mock 평가기 end-to-end.

페르소나 풀(ChromaDB)이 빌드된 환경에서, mock 작업 1건을 등록하고
status=completed 와 report_summary 생성을 검증한다.
LLM 호출이 없으므로 tokens 합계는 0.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Tuple

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.needs_persona_db]


def _post_json(url: str, body: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _wait_terminal(base_url: str, job_id: int, *, timeout_sec: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    last: dict = {}
    while time.monotonic() < deadline:
        last = _get_json(f"{base_url}/jobs/{job_id}")
        if last.get("status") in ("completed", "failed"):
            return last
        time.sleep(2)
    pytest.fail(f"job {job_id} did not finish in {timeout_sec}s. last={last}")


def test_mock_job_runs_end_to_end(stack: Tuple[str, Path], persona_db_required) -> None:
    base_url, _db = stack
    body = {
        "title": "E2E mock test",
        "text_a": "오늘부터 시작",
        "text_b": "내일부터 시작",
        "context": "신규 가입 안내 문구 A/B",
        "evaluator": "mock",
        "profile": "small",
        "max_personas": 8,
        "retrieval_k_per_bucket": 20,
        "eval_concurrency": 2,
        "seed": 42,
        "max_reason_chars": 60,
        "use_llm_task_queue": False,
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
    final = _wait_terminal(base_url, job_id, timeout_sec=180.0)
    assert final["status"] == "completed", final
    summary = final.get("report_summary") or {}
    assert "final_winner" in summary
    assert summary["final_winner"] in ("A", "B")
    # mock 경로는 LLM 호출이 없으므로 토큰 합계는 0
    assert final["tokens"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "task_count": 0,
    }
