"""build_key_reasons: 전체 표본 인용."""
from __future__ import annotations

from nemotron_ab.key_reasons import build_key_reasons


def _row(winner: str, reason: str, conf: float = 0.5, bucket: str = "30s") -> dict:
    return {
        "winner": winner,
        "reason": reason,
        "bucket": bucket,
        "confidence": conf,
        "weighted_score": {"A": 70.0 if winner == "A" else 30.0, "B": 30.0 if winner == "A" else 70.0},
    }


def test_build_key_reasons_picks_from_all_rows_by_strength() -> None:
    rows = [
        _row("B", "B약함", 0.2),
        _row("A", "A강함", 0.95),
        _row("B", "B강함", 0.9),
        _row("A", "A중간", 0.5),
    ]
    overall = {
        "count": 4,
        "win_rate": {"A": 0.5, "B": 0.5},
        "avg_score": {"A": 50.0, "B": 50.0},
        "avg_confidence": 0.3,
    }
    reasons = build_key_reasons(
        all_rows=rows,
        overall=overall,
        summary_by_bucket={},
        final_winner="A",
        max_items=3,
    )
    quote_lines = [r for r in reasons if r.startswith("【전체 표본")]
    assert len(quote_lines) == 2
    texts = " ".join(quote_lines)
    assert "A강함" in texts
    assert "B강함" in texts
    assert "B약함" not in texts
    assert "전체 표본·30대" in quote_lines[0] or any("30대" in r for r in quote_lines)
