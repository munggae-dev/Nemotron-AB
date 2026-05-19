"""리포트 synthesize 라우트·reaggregate 제거 회귀."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_jobs_router_exposes_synthesize_not_reaggregate() -> None:
    from pathlib import Path

    text = Path(__file__).resolve().parents[2].joinpath("backend", "routers", "jobs.py").read_text(
        encoding="utf-8"
    )
    assert "report/synthesize" in text
    assert "report/reaggregate" not in text
    assert "reaggregate_completed_job" not in text


def test_synthesize_job_report_persists_synthesis(fresh_conn, tmp_path: Path, isolated_sqlite) -> None:
    from nemotron_ab import db
    from nemotron_ab.report_synthesis import synthesize_job_report

    payload = {
        "llm_base_url": "http://localhost:11434/v1",
        "llm_model": "test-model",
        "max_personas": 8,
        "persona_filter": {"sex": "all", "age_min": 20, "age_max": 50},
    }
    job_id = db.enqueue_job(fresh_conn, "synth test", payload, status="running")
    db.complete_job(
        fresh_conn,
        job_id,
        report_json_path=str(tmp_path / "report.json"),
        partial_jsonl_path=str(tmp_path / "partial.jsonl"),
        summary={"final_winner": "A"},
    )
    report_obj = {
        "campaign": {"context": "ctx", "text_a": "a", "text_b": "b"},
        "report": {
            "final_winner": "A",
            "overall": {"count": 2, "win_rate": {"A": 0.5, "B": 0.5}, "avg_score": {"A": 1, "B": 0}, "avg_confidence": 0.1},
            "summary_by_bucket": {},
            "conditional_recommendation": [],
            "key_reasons": ["요약1"],
        },
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report_obj, ensure_ascii=False), encoding="utf-8")

    fake_synthesis = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "model": "test-model",
        "base_url": "http://localhost:11434/v1",
        "base_url_host": "localhost:11434",
        "tokens": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "content": {
            "headline": "H",
            "executive_summary": "E",
            "segment_notes": "",
            "action_items": [],
            "limitations": "L",
            "full_markdown": "# H",
        },
        "error": None,
    }

    with patch(
        "nemotron_ab.report_synthesis.run_synthesis_llm",
        return_value=(fake_synthesis["content"], fake_synthesis["tokens"], False),
    ):
        (tmp_path / "partial.jsonl").write_text(
            '{"persona_id":"p1","bucket":"20s","winner":"A","reason":"테스트 근거"}\n',
            encoding="utf-8",
        )
        result = synthesize_job_report(
            fresh_conn,
            job_id,
            body_base_url="http://custom/v1",
            body_model="custom-model",
        )

    assert result["status"] == "ok"
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["synthesis"]["content"]["headline"] == "H"
    assert saved["synthesis"]["model"] == "custom-model"
    assert saved["synthesis"]["inputs_used"]["persona_evaluations"][0]["reason"] == "테스트 근거"

    res = db.fetch_job_result(fresh_conn, job_id)
    summary = json.loads(res["summary_json"])
    assert summary.get("synthesis_headline") == "H"
