import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import time
import tracemalloc
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import chromadb
from sentence_transformers import SentenceTransformer

AGE_BUCKETS = ["10s", "20s", "30s", "40s"]
DEFAULT_METRIC_WEIGHTS = {
    "interest": 0.25,
    "click_intent": 0.25,
    "purchase_intent": 0.35,
    "trust": 0.15,
}

PROFILE_PRESETS = {
    "small": {"min_per_bucket": 8, "max_personas": 40, "batch_size": 8},
    "standard": {"min_per_bucket": 16, "max_personas": 80, "batch_size": 12},
}


@dataclass
class Persona:
    persona_id: str
    age: int
    bucket: str
    raw: Dict


def age_to_bucket(age: int) -> Optional[str]:
    if 10 <= age <= 19:
        return "10s"
    if 20 <= age <= 29:
        return "20s"
    if 30 <= age <= 39:
        return "30s"
    if 40 <= age <= 49:
        return "40s"
    return None


def load_personas(persona_file: Path) -> Iterable[Dict]:
    with persona_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def normalize_personas(persona_rows: Iterable[Dict]) -> List[Persona]:
    personas: List[Persona] = []
    for idx, row in enumerate(persona_rows):
        try:
            age = int(str(row.get("age", "")).strip())
        except ValueError:
            continue
        bucket = age_to_bucket(age)
        if not bucket:
            continue
        persona_id = str(row.get("id") or row.get("persona_id") or f"persona-{idx}")
        personas.append(Persona(persona_id=persona_id, age=age, bucket=bucket, raw=row))
    return personas


def normalize_persona_row(row: Dict, fallback_id: str) -> Optional[Persona]:
    try:
        age = int(str(row.get("age", "")).strip())
    except ValueError:
        return None
    bucket = age_to_bucket(age)
    if not bucket:
        return None
    persona_id = str(row.get("id") or row.get("persona_id") or row.get("uuid") or fallback_id)
    return Persona(persona_id=persona_id, age=age, bucket=bucket, raw=row)


def sample_personas_by_bucket(
    personas: List[Persona],
    min_per_bucket: int,
    max_personas: int,
    seed: int,
) -> Tuple[List[Persona], List[str]]:
    rng = random.Random(seed)
    grouped: Dict[str, List[Persona]] = {k: [] for k in AGE_BUCKETS}
    for p in personas:
        grouped[p.bucket].append(p)
    for b in AGE_BUCKETS:
        rng.shuffle(grouped[b])

    sampled: List[Persona] = []
    warnings: List[str] = []

    for bucket in AGE_BUCKETS:
        bucket_samples = grouped[bucket][:min_per_bucket]
        sampled.extend(bucket_samples)
        if len(bucket_samples) < min_per_bucket:
            warnings.append(
                f"[WARN] {bucket} 표본이 최소치({min_per_bucket})보다 부족: {len(bucket_samples)}"
            )

    if len(sampled) > max_personas:
        sampled = sampled[:max_personas]
        warnings.append(f"[WARN] 최대 페르소나 수 제한 적용: {max_personas}")

    if len(sampled) < max_personas:
        remain = max_personas - len(sampled)
        rest = []
        for bucket in AGE_BUCKETS:
            rest.extend(grouped[bucket][min_per_bucket:])
        rng.shuffle(rest)
        sampled.extend(rest[:remain])

    return sampled[:max_personas], warnings


def build_prompt(
    persona: Persona,
    campaign: Dict,
    metrics: Dict[str, float],
    max_reason_chars: int,
) -> str:
    json_schema = {
        "winner": "A 또는 B",
        "scores": {"A": {"interest": 0, "click_intent": 0, "purchase_intent": 0, "trust": 0},
                   "B": {"interest": 0, "click_intent": 0, "purchase_intent": 0, "trust": 0}},
        "reason": f"{max_reason_chars}자 이내 한 줄 근거",
    }
    metric_keys = ", ".join(metrics.keys())
    return (
        "당신은 마케팅 카피 A/B 심사 모델입니다.\n"
        "아래 페르소나 기준으로 A와 B 중 더 나은 광고 카피를 선택하세요.\n"
        f"- 평가 지표: {metric_keys}\n"
        "- 점수 범위: 각 지표 0~100 정수\n"
        "- 출력은 오직 JSON만 허용\n\n"
        f"[페르소나]\n{json.dumps(persona.raw, ensure_ascii=False)}\n\n"
        f"[캠페인 맥락]\n{json.dumps(campaign.get('context', {}), ensure_ascii=False)}\n\n"
        f"[카피 A]\n{campaign['copy_a']}\n\n"
        f"[카피 B]\n{campaign['copy_b']}\n\n"
        f"[JSON 스키마]\n{json.dumps(json_schema, ensure_ascii=False)}"
    )


def _hash_to_score(seed_text: str) -> int:
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return 30 + (int(digest[:8], 16) % 71)


def evaluate_with_mock(persona: Persona, campaign: Dict, metrics: Dict[str, float], seed: int) -> Dict:
    base_key = f"{seed}|{persona.persona_id}|{campaign['id']}"
    scores = {"A": {}, "B": {}}
    for arm in ("A", "B"):
        for metric in metrics.keys():
            scores[arm][metric] = _hash_to_score(f"{base_key}|{arm}|{metric}")

    weighted_a = weighted_sum(scores["A"], metrics)
    weighted_b = weighted_sum(scores["B"], metrics)
    winner = "A" if weighted_a >= weighted_b else "B"
    reason = (
        f"{persona.bucket}({persona.age}세) 기준 {winner}가 구매의향/신뢰도 균형이 더 우수"
    )
    return {"winner": winner, "scores": scores, "reason": reason}


def _extract_json_object(text: str) -> Dict:
    text = text.strip()
    # 모델이 코드펜스/설명을 붙이는 경우를 대비해 첫 JSON 객체를 추출
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 응답에서 JSON 객체를 찾지 못했습니다.")
    return json.loads(text[start:end + 1])


def evaluate_with_ollama(
    persona: Persona,
    campaign: Dict,
    metrics: Dict[str, float],
    max_reason_chars: int,
    ollama_url: str,
    ollama_model: str,
    ollama_timeout_sec: int,
) -> Dict:
    prompt = build_prompt(
        persona=persona,
        campaign=campaign,
        metrics=metrics,
        max_reason_chars=max_reason_chars,
    )
    payload = {
        "model": ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
        },
    }
    req = urllib.request.Request(
        url=ollama_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=ollama_timeout_sec) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    raw_response = str(data.get("response", "")).strip()
    parsed = _extract_json_object(raw_response)

    winner = parsed.get("winner")
    scores = parsed.get("scores", {})
    reason = str(parsed.get("reason", "")).strip()
    if winner not in ("A", "B"):
        raise ValueError(f"winner 값이 유효하지 않음: {winner}")
    if len(reason) > max_reason_chars:
        reason = reason[:max_reason_chars]
    for arm in ("A", "B"):
        if arm not in scores:
            raise ValueError(f"scores.{arm} 누락")
        for metric in metrics.keys():
            if metric not in scores[arm]:
                raise ValueError(f"scores.{arm}.{metric} 누락")
            scores[arm][metric] = int(scores[arm][metric])
            if scores[arm][metric] < 0:
                scores[arm][metric] = 0
            if scores[arm][metric] > 100:
                scores[arm][metric] = 100

    return {"winner": winner, "scores": scores, "reason": reason}


def weighted_sum(score_map: Dict[str, int], metric_weights: Dict[str, float]) -> float:
    return sum(score_map[k] * metric_weights[k] for k in metric_weights.keys())


def confidence_from_margin(score_a: float, score_b: float) -> float:
    margin = abs(score_a - score_b)
    # 0~100 점수대 가정에서 최대 마진을 100으로 정규화
    return min(1.0, margin / 100.0)


def evaluate_one(
    persona: Persona,
    campaign: Dict,
    metric_weights: Dict[str, float],
    retries: int,
    seed: int,
    evaluator: str,
    max_reason_chars: int,
    ollama_url: str,
    ollama_model: str,
    ollama_timeout_sec: int,
) -> Dict:
    last_error = None
    for _ in range(retries + 1):
        try:
            if evaluator == "mock":
                result = evaluate_with_mock(persona, campaign, metric_weights, seed=seed)
            else:
                result = evaluate_with_ollama(
                    persona=persona,
                    campaign=campaign,
                    metrics=metric_weights,
                    max_reason_chars=max_reason_chars,
                    ollama_url=ollama_url,
                    ollama_model=ollama_model,
                    ollama_timeout_sec=ollama_timeout_sec,
                )
            score_a = weighted_sum(result["scores"]["A"], metric_weights)
            score_b = weighted_sum(result["scores"]["B"], metric_weights)
            result["weighted_score"] = {"A": score_a, "B": score_b}
            result["confidence"] = confidence_from_margin(score_a, score_b)
            return result
        except (ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = str(e)
            continue
    return {"error": last_error or "unknown_error"}


def aggregate_results(results: List[Dict], metric_weights: Dict[str, float]) -> Dict:
    by_bucket = {b: [] for b in AGE_BUCKETS}
    for row in results:
        by_bucket[row["bucket"]].append(row)

    def summarize_rows(rows: List[Dict]) -> Dict:
        if not rows:
            return {"count": 0, "win_rate": {"A": 0.0, "B": 0.0}, "avg_score": {"A": 0.0, "B": 0.0}, "avg_confidence": 0.0}
        wins_a = sum(1 for r in rows if r["winner"] == "A")
        wins_b = len(rows) - wins_a
        avg_a = sum(r["weighted_score"]["A"] for r in rows) / len(rows)
        avg_b = sum(r["weighted_score"]["B"] for r in rows) / len(rows)
        avg_conf = sum(r.get("confidence", 0.0) for r in rows) / len(rows)
        return {
            "count": len(rows),
            "win_rate": {"A": round(wins_a / len(rows), 4), "B": round(wins_b / len(rows), 4)},
            "avg_score": {"A": round(avg_a, 4), "B": round(avg_b, 4)},
            "avg_confidence": round(avg_conf, 4),
        }

    summary_by_bucket = {b: summarize_rows(rows) for b, rows in by_bucket.items()}
    all_rows = [r for rows in by_bucket.values() for r in rows]
    overall = summarize_rows(all_rows)

    # 최종 Winner: 가중 평균 점수 우선, 동점이면 승률
    final_winner = "A"
    if overall["avg_score"]["B"] > overall["avg_score"]["A"]:
        final_winner = "B"
    elif math.isclose(overall["avg_score"]["A"], overall["avg_score"]["B"]):
        final_winner = "B" if overall["win_rate"]["B"] > overall["win_rate"]["A"] else "A"

    conditional = []
    for bucket, s in summary_by_bucket.items():
        if s["count"] == 0:
            continue
        local_winner = "A" if s["avg_score"]["A"] >= s["avg_score"]["B"] else "B"
        if local_winner != final_winner and abs(s["avg_score"]["A"] - s["avg_score"]["B"]) >= 3.0:
            conditional.append({"bucket": bucket, "winner": local_winner, "reason": "연령대별 점수 편차 큼"})

    key_reasons = []
    for row in all_rows[:50]:
        reason = row.get("reason", "").strip()
        if reason and reason not in key_reasons:
            key_reasons.append(reason)
        if len(key_reasons) >= 5:
            break

    return {
        "metric_weights": metric_weights,
        "summary_by_bucket": summary_by_bucket,
        "overall": overall,
        "final_winner": final_winner,
        "conditional_recommendation": conditional,
        "key_reasons": key_reasons[:5],
    }


def write_json(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def write_text_report(path: Path, campaign: Dict, report: Dict, warnings: List[str], runtime: Dict) -> None:
    lines = []
    lines.append("# Nemotron Persona Marketing Validation Report")
    lines.append("")
    lines.append(f"- campaign_id: {campaign['id']}")
    lines.append(f"- final_winner: {report['final_winner']}")
    lines.append(f"- elapsed_sec: {runtime['elapsed_sec']:.3f}")
    lines.append(f"- peak_memory_mb: {runtime['peak_memory_mb']:.2f}")
    lines.append("")
    lines.append("## Bucket Summary")
    for b in AGE_BUCKETS:
        s = report["summary_by_bucket"][b]
        lines.append(
            f"- {b}: count={s['count']}, win_rate(A/B)={s['win_rate']['A']:.2f}/{s['win_rate']['B']:.2f}, "
            f"avg_score(A/B)={s['avg_score']['A']:.2f}/{s['avg_score']['B']:.2f}"
        )
    if report["conditional_recommendation"]:
        lines.append("")
        lines.append("## Conditional Recommendation")
        for item in report["conditional_recommendation"]:
            lines.append(f"- {item['bucket']}: {item['winner']} ({item['reason']})")
    lines.append("")
    lines.append("## Key Reasons")
    for reason in report["key_reasons"]:
        lines.append(f"- {reason}")
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_campaign(
    personas: List[Persona],
    campaign: Dict,
    metric_weights: Dict[str, float],
    batch_size: int,
    retries: int,
    seed: int,
    partial_file: Path,
    evaluator: str,
    max_reason_chars: int,
    ollama_url: str,
    ollama_model: str,
    ollama_timeout_sec: int,
    eval_concurrency: int,
) -> List[Dict]:
    rows: List[Dict] = []
    partial_file.parent.mkdir(parents=True, exist_ok=True)
    with partial_file.open("w", encoding="utf-8") as partial:
        for i in range(0, len(personas), batch_size):
            batch = personas[i:i + batch_size]
            batch_results: Dict[str, Dict] = {}
            if evaluator == "ollama" and eval_concurrency > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=eval_concurrency) as executor:
                    future_map = {
                        executor.submit(
                            evaluate_one,
                            persona=p,
                            campaign=campaign,
                            metric_weights=metric_weights,
                            retries=retries,
                            seed=seed,
                            evaluator=evaluator,
                            max_reason_chars=max_reason_chars,
                            ollama_url=ollama_url,
                            ollama_model=ollama_model,
                            ollama_timeout_sec=ollama_timeout_sec,
                        ): p
                        for p in batch
                    }
                    for future in concurrent.futures.as_completed(future_map):
                        p = future_map[future]
                        try:
                            batch_results[p.persona_id] = future.result()
                        except Exception as e:  # noqa: BLE001
                            batch_results[p.persona_id] = {"error": str(e)}
            else:
                for p in batch:
                    batch_results[p.persona_id] = evaluate_one(
                        persona=p,
                        campaign=campaign,
                        metric_weights=metric_weights,
                        retries=retries,
                        seed=seed,
                        evaluator=evaluator,
                        max_reason_chars=max_reason_chars,
                        ollama_url=ollama_url,
                        ollama_model=ollama_model,
                        ollama_timeout_sec=ollama_timeout_sec,
                    )

            # 출력 파일 순서는 입력 순서로 고정해 재현성 유지
            for p in batch:
                result = batch_results.get(p.persona_id, {"error": "missing_result"})
                if "error" in result:
                    out = {
                        "campaign_id": campaign["id"],
                        "persona_id": p.persona_id,
                        "age": p.age,
                        "bucket": p.bucket,
                        "error": result["error"],
                    }
                else:
                    out = {
                        "campaign_id": campaign["id"],
                        "persona_id": p.persona_id,
                        "age": p.age,
                        "bucket": p.bucket,
                        "winner": result["winner"],
                        "scores": result["scores"],
                        "weighted_score": result["weighted_score"],
                        "confidence": result["confidence"],
                        "reason": result["reason"],
                    }
                partial.write(json.dumps(out, ensure_ascii=False) + "\n")
                rows.append(out)
    return [r for r in rows if "error" not in r]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nemotron Personas Korea 기반 A/B 카피 검증 MVP")
    parser.add_argument("--persona-source", choices=["file", "vectordb"], default="file")
    parser.add_argument("--persona-file", type=Path, default=Path("target_personas_10_49.jsonl"))
    parser.add_argument("--db-path", type=Path, default=Path("persona_db"))
    parser.add_argument("--collection-name", default="marketing_personas")
    parser.add_argument("--retrieval-k-per-bucket", type=int, default=200)
    parser.add_argument("--retrieval-model-name", default="jhgan/ko-sroberta-multitask")
    parser.add_argument("--retrieval-device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--campaign-file", type=Path, required=True, help="A/B 카피 입력 JSON 파일")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--profile", choices=["small", "standard"], default="small")
    parser.add_argument("--max-personas", type=int, default=0, help="0이면 profile 기본값 사용")
    parser.add_argument("--evaluator", choices=["mock", "ollama"], default="mock")
    parser.add_argument("--ollama-url", default="http://localhost:11434/api/generate")
    parser.add_argument("--ollama-model", default="gemma4:e4b-it-q4_K_M")
    parser.add_argument("--ollama-timeout-sec", type=int, default=120)
    parser.add_argument("--eval-concurrency", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--max-reason-chars", type=int, default=80)
    return parser.parse_args()


def resolve_device(device_arg: str) -> str:
    if device_arg == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001
            return "cpu"
    return device_arg


def build_retrieval_query(campaign: Dict) -> str:
    ctx = campaign.get("context", {})
    fields = [
        str(ctx.get("product", "")),
        str(ctx.get("category", "")),
        str(ctx.get("tone", "")),
        str(ctx.get("goal", "")),
        str(campaign.get("copy_a", "")),
        str(campaign.get("copy_b", "")),
    ]
    return " ".join(part for part in fields if part).strip()


def retrieve_personas_from_vectordb(
    db_path: Path,
    collection_name: str,
    retrieval_model: SentenceTransformer,
    campaign: Dict,
    max_personas: int,
    per_bucket_target: int,
    seed: int,
) -> Tuple[List[Persona], List[str]]:
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_collection(name=collection_name)
    query_text = build_retrieval_query(campaign)
    query_embedding = retrieval_model.encode(
        [query_text],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0].tolist()
    rng = random.Random(seed)
    warnings: List[str] = []

    selected: Dict[str, List[Persona]] = {b: [] for b in AGE_BUCKETS}
    for bucket in AGE_BUCKETS:
        # 10s/20s/30s/40s -> [10,19] ...
        base_age = int(bucket[:2])
        result = collection.query(
            query_embeddings=[query_embedding],
            where={
                "$and": [
                    {"age": {"$gte": base_age}},
                    {"age": {"$lte": base_age + 9}},
                ]
            },
            n_results=per_bucket_target,
            include=["documents", "metadatas"],
        )
        metadatas = result.get("metadatas", [[]])[0]
        documents = result.get("documents", [[]])[0]
        ids = result.get("ids", [[]])[0]
        for i, metadata in enumerate(metadatas):
            row = dict(metadata or {})
            row["persona"] = documents[i] if i < len(documents) else row.get("persona", "")
            row["uuid"] = ids[i] if i < len(ids) else row.get("uuid", f"retrieved-{bucket}-{i}")
            normalized = normalize_persona_row(row, fallback_id=f"retrieved-{bucket}-{i}")
            if normalized:
                selected[bucket].append(normalized)
        rng.shuffle(selected[bucket])
        if len(selected[bucket]) < per_bucket_target:
            warnings.append(
                f"[WARN] VectorDB {bucket} 검색 결과가 목표({per_bucket_target})보다 적음: {len(selected[bucket])}"
            )

    merged: List[Persona] = []
    # 연령대 균등 우선 추출
    round_idx = 0
    while len(merged) < max_personas:
        progressed = False
        for bucket in AGE_BUCKETS:
            if round_idx < len(selected[bucket]) and len(merged) < max_personas:
                merged.append(selected[bucket][round_idx])
                progressed = True
        if not progressed:
            break
        round_idx += 1

    if len(merged) < max_personas:
        warnings.append(f"[WARN] VectorDB에서 확보된 페르소나 수가 목표({max_personas})보다 적음: {len(merged)}")

    return merged, warnings


def main() -> None:
    args = parse_args()
    tracemalloc.start()
    t0 = time.perf_counter()

    profile = PROFILE_PRESETS[args.profile]
    max_personas = args.max_personas if args.max_personas > 0 else profile["max_personas"]
    metric_weights = DEFAULT_METRIC_WEIGHTS.copy()
    warnings: List[str] = []

    if not args.campaign_file.exists():
        raise FileNotFoundError(f"campaign file not found: {args.campaign_file}")

    campaigns = json.loads(args.campaign_file.read_text(encoding="utf-8"))
    if not isinstance(campaigns, list) or not campaigns:
        raise ValueError("campaign-file must contain a non-empty JSON array")

    sampled: List[Persona] = []
    retrieval_model: Optional[SentenceTransformer] = None
    if args.persona_source == "file":
        if not args.persona_file.exists():
            raise FileNotFoundError(f"persona file not found: {args.persona_file}")
        personas = normalize_personas(load_personas(args.persona_file))
        sampled, sample_warnings = sample_personas_by_bucket(
            personas=personas,
            min_per_bucket=profile["min_per_bucket"],
            max_personas=max_personas,
            seed=args.seed,
        )
        warnings.extend(sample_warnings)
    else:
        retrieval_model = SentenceTransformer(
            args.retrieval_model_name,
            device=resolve_device(args.retrieval_device),
        )

    for campaign in campaigns:
        required = {"id", "copy_a", "copy_b", "context"}
        if not required.issubset(set(campaign.keys())):
            raise ValueError(f"campaign format invalid: required keys {sorted(required)}")

        if args.persona_source == "vectordb":
            sampled, retrieval_warnings = retrieve_personas_from_vectordb(
                db_path=args.db_path,
                collection_name=args.collection_name,
                retrieval_model=retrieval_model,
                campaign=campaign,
                max_personas=max_personas,
                per_bucket_target=args.retrieval_k_per_bucket,
                seed=args.seed,
            )
            warnings.extend(retrieval_warnings)
            if not sampled:
                raise ValueError("vectordb에서 페르소나를 가져오지 못했습니다.")

        # 프롬프트 템플릿 생성(디버그/검증 목적)
        _ = build_prompt(
            persona=sampled[0],
            campaign=campaign,
            metrics=metric_weights,
            max_reason_chars=args.max_reason_chars,
        )

        partial_file = args.output_dir / f"{campaign['id']}.partial.jsonl"
        rows = run_campaign(
            personas=sampled,
            campaign=campaign,
            metric_weights=metric_weights,
            batch_size=profile["batch_size"],
            retries=args.retries,
            seed=args.seed,
            partial_file=partial_file,
            evaluator=args.evaluator,
            max_reason_chars=args.max_reason_chars,
            ollama_url=args.ollama_url,
            ollama_model=args.ollama_model,
            ollama_timeout_sec=args.ollama_timeout_sec,
            eval_concurrency=args.eval_concurrency,
        )
        report = aggregate_results(rows, metric_weights=metric_weights)

        current, peak = tracemalloc.get_traced_memory()
        del current
        runtime = {"elapsed_sec": time.perf_counter() - t0, "peak_memory_mb": peak / (1024 * 1024)}

        report_json = {
            "campaign": campaign,
            "profile": args.profile,
            "seed": args.seed,
            "warnings": warnings,
            "runtime": runtime,
            "report": report,
        }

        write_json(args.output_dir / f"{campaign['id']}.report.json", report_json)
        write_text_report(
            args.output_dir / f"{campaign['id']}.report.md",
            campaign=campaign,
            report=report,
            warnings=warnings,
            runtime=runtime,
        )

    tracemalloc.stop()
    print(f"완료: {len(campaigns)}개 캠페인 검증, 출력 경로={args.output_dir}")


if __name__ == "__main__":
    main()
