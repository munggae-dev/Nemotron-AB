from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.schemas.jobs import ImageRefIn, JobCreate, PersonaFilterIn
from backend.services.job_payload import payload_from_create
from nemotron_ab import laya_eval
from scripts.ab_validator import DEFAULT_METRIC_WEIGHTS, Persona


def test_laya_default_and_unsupported_inputs():
    body = JobCreate(text_a="첫 달 무료", text_b="10% 할인", persona_filter=PersonaFilterIn())
    assert body.evaluator == "laya"
    assert payload_from_create(body)["evaluator"] == "laya"
    body.image_a = ImageRefIn(type="url", value="https://example.com/image.png")
    with pytest.raises(HTTPException, match="텍스트 평가용"):
        payload_from_create(body)
    body.image_a = None
    body.use_llm_task_queue = False
    with pytest.raises(HTTPException, match="태스크 큐"):
        payload_from_create(body)


@pytest.mark.parametrize(
    "bad_usage", [{"truncated": True}, {"state_tokens_dropped": 1}, {"options": {"lost": 1}}]
)
def test_laya_refuses_silent_input_loss(monkeypatch, bad_usage):
    class FakeAgent:
        def predict(self, *_args, **_kwargs):
            return {"usage": bad_usage, "answers": {}}

    monkeypatch.setattr(laya_eval, "_get_agent", lambda: FakeAgent())
    persona = Persona("p", 30, "30s", {"age": 30})
    with pytest.raises(ValueError, match="한도"):
        laya_eval.evaluate_persona_laya(persona, {"text_a": "A", "text_b": "B"}, DEFAULT_METRIC_WEIGHTS)


def test_laya_evaluates_arms_independently_without_generated_tokens(monkeypatch):
    class FakeAgent:
        def predict(self, state, questions, **_kwargs):
            p = 0.8 if state["문구"] == "무료 체험" else 0.2
            return {
                "answers": {key: {"probabilities": {"A": p, "B": 1 - p}} for key in questions},
                "usage": {"input_tokens": 100, "output_tokens": 0, "truncated": False},
            }

    monkeypatch.setattr(laya_eval, "_get_agent", lambda: FakeAgent())
    persona = Persona("p", 30, "30s", {"age": 30})
    result, usage = laya_eval.evaluate_persona_laya(
        persona, {"text_a": "무료 체험", "text_b": "유료 가입"}, DEFAULT_METRIC_WEIGHTS
    )
    swapped, _ = laya_eval.evaluate_persona_laya(
        persona, {"text_a": "유료 가입", "text_b": "무료 체험"}, DEFAULT_METRIC_WEIGHTS
    )
    assert result["scores"]["A"] == swapped["scores"]["B"]
    assert result["scores"]["B"] == swapped["scores"]["A"]
    assert (result["winner"], swapped["winner"]) == ("A", "B")
    assert usage == {"prompt_tokens": 200, "completion_tokens": 0, "total_tokens": 200}
    assert result["engine"]["name"] == "laya"


def test_chroma_metadata_order_does_not_change_model_input(monkeypatch):
    inputs = []

    class FakeAgent:
        def predict(self, state, questions, **_kwargs):
            import json

            inputs.append(json.dumps(state, ensure_ascii=False))
            return {
                "answers": {key: {"probabilities": {"A": 0.6, "B": 0.4}} for key in questions},
                "usage": {"input_tokens": 100},
            }

    monkeypatch.setattr(laya_eval, "_get_agent", lambda: FakeAgent())
    campaign = {"text_a": "무료 체험", "text_b": "할인 가입"}
    for raw in ({"age": 30, "persona": "직장인"}, {"persona": "직장인", "age": 30}):
        laya_eval.evaluate_persona_laya(Persona("p", 30, "30s", raw), campaign, DEFAULT_METRIC_WEIGHTS)
    assert inputs[:2] == inputs[2:]
