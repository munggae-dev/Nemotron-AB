"""Measure real API jobs; requires a running API, worker and persona DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8010")
    parser.add_argument("--evaluator", choices=("laya", "openai"), required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[8, 8, 24])
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--llm-model", default="gemma4:e2b-it-q4_K_M")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-sec", type=float, default=900)
    args = parser.parse_args()
    if any(size < 8 or size > 200 for size in args.sizes):
        parser.error("sizes must be between 8 and 200")
    if args.timeout_sec <= 0:
        parser.error("timeout must be positive")
    api_base = args.api_base.rstrip("/")
    root = Path(__file__).resolve().parents[1]

    def request(path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(api_base + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    records = []
    for iteration, size in enumerate(args.sizes):
        body = {
            "title": f"{args.evaluator} benchmark {iteration + 1}: {size} personas",
            "text_a": "첫 달 무료로 체험하고 결정하세요",
            "text_b": "지금 결제하면 구독료 10% 할인",
            "context": "직장인을 위한 생산성 도구의 구독 안내 문구 A/B 평가",
            "evaluator": args.evaluator,
            "max_personas": size,
            "retrieval_k_per_bucket": 80,
            "eval_concurrency": 2,
            "seed": 42,
            "profile": "small",
            "prompt_profile": "full",
            "max_persona_chars": 1500,
            "max_reason_chars": 80,
            "response_format_json": False,
            "use_llm_task_queue": True,
            "persona_filter": {"sex": "all", "age_min": 20, "age_max": 50},
        }
        if args.evaluator == "openai":
            body.update(llm_base_url=args.llm_base_url, llm_model=args.llm_model)
        started = time.perf_counter()
        job_id = request("/jobs", body)["id"]
        history = []
        while time.perf_counter() - started < args.timeout_sec:
            job = request(f"/jobs/{job_id}")
            elapsed = time.perf_counter() - started
            if not history or job["status"] != history[-1]["status"]:
                history.append({"status": job["status"], "observed_sec": round(elapsed, 3)})
                print(job_id, history[-1], flush=True)
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        if job["status"] != "completed":
            raise RuntimeError(f"Job {job_id} did not complete: {job}")
        report = request(f"/jobs/{job_id}/report")
        partial = root / f"outputs/jobs/job_{job_id}/partial.jsonl"
        rows = [json.loads(line) for line in partial.read_text().splitlines()]
        if len(rows) != size:
            raise RuntimeError(f"Job {job_id}: expected {size} completed personas, got {len(rows)}")
        selection = sorted(row["persona_id"] for row in rows)
        digest = hashlib.sha256(json.dumps(selection).encode()).hexdigest()
        records.append(
            {
                "job_id": job_id,
                "personas": size,
                "iteration": iteration + 1,
                "total_sec": round(elapsed, 3),
                "status_history": history,
                "selection_sha256": digest,
                "tokens": job["tokens"],
                "final_winner": report["report"]["final_winner"],
                "evaluation_engine": report.get("evaluation_engine"),
                "request": body,
                "results": rows,
            }
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        print(f"Job {job_id}: {size} personas in {elapsed:.3f}s", flush=True)


if __name__ == "__main__":
    main()
