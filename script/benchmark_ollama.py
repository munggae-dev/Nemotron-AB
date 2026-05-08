import argparse
import json
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ollama 평가 성능 벤치마크")
    parser.add_argument("--campaign-file", type=Path, default=Path("script/sample_campaigns.json"))
    parser.add_argument("--db-path", type=Path, default=Path("persona_db"))
    parser.add_argument("--collection-name", default="marketing_personas")
    parser.add_argument("--ollama-model", default="gemma4:e4b-it-q4_K_M")
    parser.add_argument("--max-personas", type=int, default=16)
    parser.add_argument("--retrieval-k-per-bucket", type=int, default=80)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--concurrency-values", default="1,2,4,6")
    parser.add_argument("--output-root", type=Path, default=Path("outputs/benchmark_ollama"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    # 벤치 속도를 위해 첫 캠페인만 사용
    campaigns = json.loads(args.campaign_file.read_text(encoding="utf-8"))
    first_campaign_file = args.output_root / "one_campaign.json"
    first_campaign_file.write_text(
        json.dumps([campaigns[0]], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    results = []
    concurrencies = [int(x.strip()) for x in args.concurrency_values.split(",") if x.strip()]
    for c in concurrencies:
        out_dir = args.output_root / f"c{c}"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "./venv/bin/python",
            "script/marketing_validator.py",
            "--persona-source",
            "vectordb",
            "--db-path",
            str(args.db_path),
            "--collection-name",
            args.collection_name,
            "--campaign-file",
            str(first_campaign_file),
            "--profile",
            "small",
            "--max-personas",
            str(args.max_personas),
            "--retrieval-k-per-bucket",
            str(args.retrieval_k_per_bucket),
            "--output-dir",
            str(out_dir),
            "--evaluator",
            "ollama",
            "--ollama-model",
            args.ollama_model,
            "--ollama-timeout-sec",
            str(args.timeout_sec),
            "--retrieval-device",
            "cuda",
            "--eval-concurrency",
            str(c),
        ]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        elapsed = time.perf_counter() - t0
        ok = proc.returncode == 0
        results.append(
            {
                "concurrency": c,
                "ok": ok,
                "elapsed_sec_wall": round(elapsed, 3),
                "returncode": proc.returncode,
                "stdout_tail": "\n".join(proc.stdout.strip().splitlines()[-3:]),
                "stderr_tail": "\n".join(proc.stderr.strip().splitlines()[-3:]),
            }
        )

    valid = [r for r in results if r["ok"]]
    best = min(valid, key=lambda x: x["elapsed_sec_wall"]) if valid else None
    summary = {
        "model": args.ollama_model,
        "max_personas": args.max_personas,
        "retrieval_k_per_bucket": args.retrieval_k_per_bucket,
        "results": results,
        "best": best,
    }
    (args.output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
