"""report_synthesis: LLM 설정 우선순위·콘텐츠 정규화."""
from __future__ import annotations

import json
import sys
import types

import pytest

from nemotron_ab.report_synthesis import (
    _normalize_synthesis_content,
    build_persona_evaluations_payload,
    build_synthesis_inputs_used,
    build_synthesis_message_content,
    build_synthesis_prompt,
    load_partial_eval_rows,
    resolve_synthesis_llm_config,
    run_synthesis_llm,
)


def test_resolve_synthesis_llm_config_body_over_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_SYNTHESIS_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_SYNTHESIS_MODEL", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    cfg = resolve_synthesis_llm_config(
        body_base_url="http://body/v1",
        body_model="body-model",
        job_payload={"llm_base_url": "http://job/v1", "llm_model": "job-model"},
    )
    assert cfg.base_url == "http://body/v1"
    assert cfg.model == "body-model"
    assert cfg.temperature == 0.2


def test_resolve_synthesis_llm_config_payload_over_synthesis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_SYNTHESIS_BASE_URL", "http://syn/v1")
    monkeypatch.setenv("LLM_SYNTHESIS_MODEL", "syn-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    cfg = resolve_synthesis_llm_config(
        job_payload={"llm_base_url": "http://job/v1", "llm_model": "job-model"},
    )
    assert cfg.base_url == "http://job/v1"
    assert cfg.model == "job-model"


def test_resolve_synthesis_llm_config_synthesis_env_when_payload_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_SYNTHESIS_BASE_URL", "http://syn/v1")
    monkeypatch.setenv("LLM_SYNTHESIS_MODEL", "syn-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    cfg = resolve_synthesis_llm_config(job_payload={})
    assert cfg.base_url == "http://syn/v1"
    assert cfg.model == "syn-model"


def test_load_partial_eval_rows(tmp_path) -> None:
    p = tmp_path / "partial.jsonl"
    p.write_text(
        '{"persona_id":"p1","winner":"A","reason":"r1"}\n'
        '{"persona_id":"p2","winner":"B","reason":"r2"}\n',
        encoding="utf-8",
    )
    rows = load_partial_eval_rows(p)
    assert len(rows) == 2
    assert rows[0]["persona_id"] == "p1"


def test_build_synthesis_prompt_includes_full_persona_evaluations() -> None:
    persona_rows = [
        {
            "persona_id": "p1",
            "age": 28,
            "bucket": "20s",
            "winner": "A",
            "weighted_score": {"A": 70, "B": 60},
            "confidence": 0.4,
            "reason": "가격이 낫다",
        },
        {
            "persona_id": "p2",
            "age": 35,
            "bucket": "30s",
            "winner": "B",
            "weighted_score": {"A": 55, "B": 72},
            "confidence": 0.5,
            "reason": "디자인이 낫다",
        },
    ]
    prompt = build_synthesis_prompt(
        campaign={"context": "ctx", "text_a": "A", "text_b": "B"},
        report={
            "final_winner": "B",
            "overall": {"count": 2},
            "summary_by_bucket": {},
            "conditional_recommendation": [],
            "key_reasons": ["요약 한 줄"],
        },
        persona_evaluations=persona_rows,
    )
    assert "[페르소나별 평가 전체 표본]" in prompt
    assert "가격이 낫다" in prompt
    assert "디자인이 낫다" in prompt
    assert "표본 전체" in prompt


def test_build_persona_evaluations_payload_truncates_when_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_SYNTHESIS_MAX_EVAL_JSON_CHARS", "200")
    rows = [{"persona_id": f"p{i}", "reason": "x" * 80} for i in range(20)]
    compact, meta = build_persona_evaluations_payload(rows)
    assert meta["total_rows"] == 20
    assert meta["truncated"] is True
    assert len(compact) < 20


def test_build_synthesis_inputs_used_snapshot() -> None:
    rows = [{"persona_id": "p1", "winner": "A", "reason": "r1"}]
    compact, meta = build_persona_evaluations_payload(rows)
    snap = build_synthesis_inputs_used(
        campaign={"context": "ctx", "text_a": "a", "text_b": "b"},
        report={"final_winner": "B", "key_reasons": ["k"], "overall": {"count": 1}},
        persona_evaluations=compact,
        persona_evaluations_meta=meta,
        multimodal=True,
    )
    assert snap["context"] == "ctx"
    assert snap["persona_evaluations"][0]["reason"] == "r1"
    assert snap["aggregation"]["final_winner"] == "B"
    assert snap["multimodal"] is True


def test_build_synthesis_prompt_includes_context_and_key_reasons() -> None:
    prompt = build_synthesis_prompt(
        campaign={"context": "테스트 맥락", "text_a": "A카피", "text_b": "B카피"},
        report={
            "final_winner": "B",
            "overall": {"count": 10},
            "summary_by_bucket": {},
            "conditional_recommendation": [],
            "key_reasons": ["표본 10건", "B 우세"],
        },
    )
    assert "테스트 맥락" in prompt
    assert "B카피" in prompt
    assert "표본 10건" in prompt


def test_normalize_synthesis_content_builds_full_markdown() -> None:
    out = _normalize_synthesis_content(
        {
            "headline": "Variant B 추천",
            "executive_summary": "요약 본문",
            "action_items": ["A/B 테스트 확대"],
            "limitations": "시뮬레이션 한계",
        }
    )
    assert out["headline"] == "Variant B 추천"
    assert "요약 본문" in out["full_markdown"]
    assert "A/B 테스트 확대" in out["full_markdown"]


def test_run_synthesis_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "headline": "결론",
            "executive_summary": "본문",
            "segment_notes": "",
            "action_items": [],
            "limitations": "한계",
            "full_markdown": "",
        },
        ensure_ascii=False,
    )

    class _FakeResp:
        content = payload
        usage_metadata = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    class _FakeLlm:
        def invoke(self, _messages: object) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr(
        "nemotron_ab.report_synthesis.make_chat_llm",
        lambda *_args, **_kwargs: _FakeLlm(),
    )

    class _HumanMessage:
        def __init__(self, content: object) -> None:
            self.content = content

    lc_messages = types.ModuleType("langchain_core.messages")
    lc_messages.HumanMessage = _HumanMessage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_core.messages", lc_messages)
    if "langchain_core" not in sys.modules:
        monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))

    from nemotron_ab.llm_provider import LLMConfig

    content, usage, used_multimodal = run_synthesis_llm(
        campaign={"context": "c", "text_a": "a", "text_b": "b"},
        report={
            "final_winner": "A",
            "key_reasons": ["r"],
            "overall": {},
            "summary_by_bucket": {},
            "conditional_recommendation": [],
        },
        llm_config=LLMConfig(base_url="http://fake/v1", model="fake", api_key="EMPTY"),
    )
    assert content["headline"] == "결론"
    assert usage["total_tokens"] == 150
    assert used_multimodal is False


def test_build_synthesis_message_content_multimodal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nemotron_ab.report_synthesis.image_ref_to_data_url",
        lambda ref, max_dim=None: f"data:image/png;base64,{ref.get('value', '')}",
    )
    parts = build_synthesis_message_content(
        campaign={
            "context": "ctx",
            "text_a": "a",
            "text_b": "b",
            "image_a": {"type": "path", "value": "a.png"},
            "image_b": {"type": "path", "value": "b.png"},
        },
        report={
            "final_winner": "B",
            "key_reasons": ["k"],
            "overall": {},
            "summary_by_bucket": {},
            "conditional_recommendation": [],
        },
    )
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert "시각 자료" in str(parts[0]["text"])
    image_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts) == 2
