"""Local LAYA judgments, adapted to the existing per-persona report format."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from nemotron_ab.prompt_profile import truncate_persona_view
from scripts.ab_validator import Persona, campaign_has_images, confidence_from_margin, weighted_sum

MODEL_ID = "convaiinnovations/laya-multilingual"
SCORE_NOTE = "LAYA 모델 확률을 0~100으로 환산한 합성 평가이며, 실제 클릭률·구매율이나 한국어 정확도를 보장하지 않습니다."
METRICS = {
    "interest": ("관심을 갖는가?", "관심을 갖는다", "관심을 갖지 않는다"),
    "click_intent": ("자세히 보기 위해 클릭하려 하는가?", "클릭하려 한다", "클릭하려 하지 않는다"),
    "purchase_intent": (
        "제안된 상품이나 서비스에 돈을 지불하고 구매할 의향이 있는가? 무료 체험만 시작하는 의향과 구분하세요.",
        "유료 구매나 유료 구독을 위해 돈을 지불할 의향이 있다",
        "유료 구매나 유료 구독을 위해 돈을 지불할 의향이 없다",
    ),
    "trust": ("문구를 신뢰하는가?", "신뢰한다", "신뢰하지 않는다"),
}
_LOCK = threading.Lock()
_AGENT: Any = None


def _get_agent() -> Any:
    global _AGENT
    if _AGENT is None:
        from laya import Agent

        default_path = Path(__file__).resolve().parents[1] / "models/laya-multilingual"
        _AGENT = Agent(
            os.environ.get("LAYA_MODEL_PATH", str(default_path)),
            device=os.environ.get("LAYA_DEVICE", "auto"),
            backend="eager",
        )
        if os.environ.get("LAYA_DEVICE") == "cuda" and _AGENT.device.type != "cuda":
            _AGENT = None
            raise RuntimeError("LAYA CUDA 요청이 CPU로 폴백했습니다. GPU 실행 환경을 확인하세요.")
    return _AGENT


def evaluate_persona_laya(
    persona: Persona,
    campaign: dict[str, Any],
    metrics: dict[str, float],
    max_reason_chars: int = 80,
    *,
    max_persona_chars: int = 1500,
) -> tuple[dict[str, Any], dict[str, int]]:
    if campaign_has_images(campaign):
        raise ValueError(
            "LAYA multilingual은 텍스트 평가용입니다. 이미지 평가는 OpenAI-호환 평가기를 선택하세요."
        )
    unknown = set(metrics) - METRICS.keys()
    if unknown:
        raise ValueError(f"Unsupported LAYA metrics: {sorted(unknown)}")
    questions = {}
    for metric in metrics:
        instruction, positive, negative = METRICS[metric]
        for order in (0, 1):
            questions[f"{metric}_{order}"] = {
                "type": "choice",
                "instructions": f"주어진 페르소나가 맥락 속 문구에 {instruction}",
                "criteria": {"A": f"이 페르소나는 {positive}", "B": f"이 페르소나는 {negative}"},
                "option_order": [0, 1] if order == 0 else [1, 0],
            }
    # Chroma metadata arrives in hash-map order; make both truncation and prompts stable.
    canonical_persona = json.loads(json.dumps(persona.raw, ensure_ascii=False, sort_keys=True))
    view = truncate_persona_view(canonical_persona, max_chars=max_persona_chars)
    scores: dict[str, dict[str, int]] = {}
    probabilities: dict[str, dict[str, float]] = {}
    order_gaps: dict[str, dict[str, float]] = {}
    input_tokens = 0
    started = time.perf_counter()
    # One model per worker, including during concurrent first-use requests.
    with _LOCK:
        agent = _get_agent()
        for arm in ("A", "B"):
            state = {
                "문구": campaign[f"text_{arm.lower()}"],
                "맥락": campaign.get("context", ""),
                "페르소나": view,
            }
            result = agent.predict(
                state,
                questions,
                lang="ko",
                max_len=int(os.environ.get("LAYA_MAX_LEN", "8192")),
                head_max_len=256,
            )
            usage = result["usage"]
            if usage.get("truncated") or usage.get("state_tokens_dropped", 0):
                raise ValueError(
                    "LAYA 입력 토큰 한도를 초과했습니다. 문구·맥락 또는 페르소나 길이를 줄이세요."
                )
            if usage.get("options"):
                raise ValueError("LAYA 선택지 토큰 한도를 초과했습니다.")
            input_tokens += int(usage.get("input_tokens", 0))
            scores[arm], probabilities[arm], order_gaps[arm] = {}, {}, {}
            for metric in metrics:
                pair = []
                for order in (0, 1):
                    probs = result["answers"][f"{metric}_{order}"]["probabilities"]
                    values = [float(probs[key]) for key in ("A", "B")]
                    if (
                        not all(math.isfinite(x) and 0 <= x <= 1 for x in values)
                        or abs(sum(values) - 1) > 0.01
                    ):
                        raise ValueError("Invalid LAYA probabilities")
                    pair.append(values[0])
                probability = sum(pair) / 2
                scores[arm][metric] = round(100 * probability)
                probabilities[arm][metric] = round(probability, 6)
                order_gaps[arm][metric] = round(abs(pair[0] - pair[1]), 6)
    weighted = {arm: weighted_sum(scores[arm], metrics) for arm in ("A", "B")}
    winner = "A" if weighted["A"] >= weighted["B"] else "B"
    result = {
        "winner": winner,
        "scores": scores,
        "weighted_score": weighted,
        "confidence": confidence_from_margin(weighted["A"], weighted["B"]),
        "reason": f"LAYA 확률 기반 가중 점수: A {weighted['A']:.1f}, B {weighted['B']:.1f}"[
            :max_reason_chars
        ],
        "engine": {
            "name": "laya",
            "model": MODEL_ID,
            "revision": os.environ.get("LAYA_MODEL_REVISION", "local"),
            "device": str(getattr(agent, "device", "unknown")),
            "dtype": str(getattr(agent, "dtype", "unknown")),
            "method": "binary-choice-probability-order-average-v2",
            "probabilities": probabilities,
            "option_order_gaps": order_gaps,
            "predict_calls": 2,
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "score_note": SCORE_NOTE,
        },
    }
    return result, {"prompt_tokens": input_tokens, "completion_tokens": 0, "total_tokens": input_tokens}
