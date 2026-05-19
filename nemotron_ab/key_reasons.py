"""집계 리포트용 핵심 인사이트(key_reasons) 생성."""
from __future__ import annotations

from typing import Any

AGE_BUCKETS = ["20s", "30s", "40s", "50s"]
BUCKET_LABEL_KO = {"20s": "20대", "30s": "30대", "40s": "40대", "50s": "50대"}


def _quote_strength(row: dict) -> tuple[float, float]:
    conf = float(row.get("confidence") or 0.0)
    ws = row.get("weighted_score") or {}
    try:
        a = float(ws.get("A", 0.0))
        b = float(ws.get("B", 0.0))
    except (TypeError, ValueError):
        a, b = 0.0, 0.0
    margin = abs(a - b)
    return (conf, margin)


def _format_quote_line(row: dict) -> str | None:
    reason = str(row.get("reason", "")).strip()
    if not reason:
        return None
    arm = str(row.get("winner", "")).strip().upper()
    if arm not in ("A", "B"):
        arm = "?"
    bucket = str(row.get("bucket", "")).strip()
    bucket_label = BUCKET_LABEL_KO.get(bucket, bucket)
    if bucket_label:
        return f"【전체 표본·{bucket_label}·안 {arm} 선호】 {reason}"
    return f"【전체 표본·안 {arm} 선호】 {reason}"


def _quotes_from_all_rows(all_rows: list[dict], *, max_quotes: int) -> list[str]:
    """전체 평가 표본에서 신뢰도·점수차가 큰 순으로 reason을 고른다(안 A/B 필터 없음)."""
    if max_quotes <= 0:
        return []
    ranked = sorted(all_rows, key=_quote_strength, reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for row in ranked:
        line = _format_quote_line(row)
        if not line:
            continue
        reason = str(row.get("reason", "")).strip()
        if reason in seen:
            continue
        seen.add(reason)
        out.append(line)
        if len(out) >= max_quotes:
            break
    return out


def build_key_reasons(
    *,
    all_rows: list[dict],
    overall: dict[str, Any],
    summary_by_bucket: dict[str, dict],
    final_winner: str,
    max_items: int = 10,
) -> list[str]:
    """집계 수치를 먼저 밝히고, 전체 평가 표본에서 LLM 근거를 인용한다."""
    n = int(overall.get("count") or 0)
    if n <= 0:
        return ["평가 결과 행이 없어 핵심 인사이트를 생성하지 못했습니다."]

    wr_a = float(overall["win_rate"]["A"])
    wr_b = float(overall["win_rate"]["B"])
    sa = float(overall["avg_score"]["A"])
    sb = float(overall["avg_score"]["B"])
    avg_conf = float(overall.get("avg_confidence") or 0.0)

    lines: list[str] = [
        (
            f"전체 표본 {n}건 기준 우세 비율 A {wr_a:.1%} / B {wr_b:.1%}, "
            f"평균 가중 점수 A {sa:.2f} · B {sb:.2f}, "
            f"표본 평균 신뢰도 지표(점수 차 기반) {avg_conf:.1%}. "
            f"집계 규칙(가중 점수 우선·동점 시 승률)에 따라 최종 추천은 Variant {final_winner}입니다."
        )
    ]

    bucket_bits: list[str] = []
    for b in AGE_BUCKETS:
        s = summary_by_bucket.get(b) or {}
        cnt = int(s.get("count") or 0)
        if cnt <= 0:
            continue
        label = BUCKET_LABEL_KO.get(b, b)
        bwr_a = float(s["win_rate"]["A"])
        bwr_b = float(s["win_rate"]["B"])
        dom = "A" if bwr_a >= bwr_b else "B"
        dom_wr = bwr_a if dom == "A" else bwr_b
        bsa = float(s["avg_score"]["A"])
        bsb = float(s["avg_score"]["B"])
        bucket_bits.append(
            f"{label} n={cnt} · {dom} 우세 {dom_wr:.0%}(승률 A {bwr_a:.0%}/B {bwr_b:.0%}, "
            f"평균점수 A {bsa:.1f}/B {bsb:.1f})"
        )
    if bucket_bits:
        lines.append("연령대별 요약: " + " / ".join(bucket_bits))

    max_quotes = max(0, max_items - len(lines))
    lines.extend(_quotes_from_all_rows(all_rows, max_quotes=max_quotes))

    return lines[:max_items]
