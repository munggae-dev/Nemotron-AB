"""Replay a local job snapshot against a separately configured H2O server."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nemotron_ab.laya_eval import METRICS  # noqa: E402
from nemotron_ab.prompt_profile import truncate_persona_view  # noqa: E402
from scripts.ab_validator import DEFAULT_METRIC_WEIGHTS, normalize_persona_row, weighted_sum  # noqa: E402


def normalize(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {normalize(k): normalize(v) for k, v in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "nemotron_ab/app.sqlite3")
    parser.add_argument("--url", default="http://127.0.0.1:8762")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.concurrency < 1 or args.concurrency > 32:
        parser.error("concurrency must be between 1 and 32")
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        tasks = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT payload_json FROM job_tasks WHERE job_id=? ORDER BY id", (args.job_id,)
            )
        ]
    if not tasks:
        parser.error("job has no persona tasks")
    questions = {}
    for metric, (instruction, positive, negative) in METRICS.items():
        for order in (0, 1):
            pairs = [("A", "이 페르소나는 " + positive), ("B", "이 페르소나는 " + negative)]
            questions[f"{metric}_{order}"] = {
                "type": "choice",
                "instructions": "주어진 페르소나가 맥락 속 문구에 " + instruction,
                "criteria": dict(pairs if order == 0 else reversed(pairs)),
            }

    def evaluate(task):
        persona = normalize_persona_row(task["persona_row"], fallback_id="sample")
        if persona is None:
            raise ValueError("invalid persona")
        view = truncate_persona_view(
            json.loads(json.dumps(persona.raw, ensure_ascii=False, sort_keys=True)), 1500
        )
        scores, probabilities = {}, {}
        for arm in ("A", "B"):
            payload = {
                "state": {
                    "문구": task["campaign"]["text_" + arm.lower()],
                    "맥락": task["campaign"]["context"],
                    "페르소나": view,
                },
                "questions": questions,
            }
            req = urllib.request.Request(
                args.url.rstrip("/") + "/v1/systemone",
                data=json.dumps(normalize(payload), ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.load(response)
            probabilities[arm] = {
                m: sum(result["answers"][f"{m}_{i}"]["probabilities"]["A"] for i in (0, 1)) / 2
                for m in METRICS
            }
            scores[arm] = {m: round(100 * p) for m, p in probabilities[arm].items()}
        weighted = {arm: weighted_sum(scores[arm], DEFAULT_METRIC_WEIGHTS) for arm in ("A", "B")}
        return {
            "persona_id": persona.persona_id,
            "scores": scores,
            "probabilities": probabilities,
            "weighted_score": weighted,
            "winner": "A" if weighted["A"] >= weighted["B"] else "B",
        }

    evaluate(tasks[0])  # Warm-up is excluded from the measured interval.
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(evaluate, tasks))
    output = {
        "job_id": args.job_id,
        "clients": args.concurrency,
        "seconds": time.perf_counter() - started,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f'{len(results)} personas: {output["seconds"]:.3f}s')


if __name__ == "__main__":
    main()
