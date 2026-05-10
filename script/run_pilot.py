import argparse
import json
import subprocess
import time
from pathlib import Path
from statistics import pstdev

ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="마케팅 검증 MVP 파일럿 실행기")
    parser.add_argument("--persona-file", type=Path, default=Path("target_personas_20_59.jsonl"))
    parser.add_argument("--campaign-file", type=Path, default=Path("script/sample_campaigns.json"))
    parser.add_argument("--profile", choices=["small", "standard"], default="small")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/pilot"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    winners = []
    elapsed_sec = []
    peak_memory_mb = []

    for i in range(args.runs):
        run_dir = args.output_root / f"run_{i + 1}"
        run_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        subprocess.run(
            [
                str(ROOT_DIR / "venv" / "bin" / "python"),
                str(ROOT_DIR / "script" / "marketing_validator.py"),
                "--persona-file",
                str(args.persona_file),
                "--campaign-file",
                str(args.campaign_file),
                "--profile",
                args.profile,
                "--seed",
                str(42 + i),
                "--output-dir",
                str(run_dir),
            ],
            check=True,
            cwd=str(ROOT_DIR),
        )
        elapsed_sec.append(time.perf_counter() - t0)

        # 첫 캠페인 리포트를 기준으로 파일럿 지표 요약
        report_files = sorted(run_dir.glob("*.report.json"))
        if report_files:
            obj = json.loads(report_files[0].read_text(encoding="utf-8"))
            winners.append(obj["report"]["final_winner"])
            peak_memory_mb.append(obj["runtime"]["peak_memory_mb"])

    winner_stability = {}
    for w in winners:
        winner_stability[w] = winner_stability.get(w, 0) + 1

    summary = {
        "runs": args.runs,
        "profile": args.profile,
        "winner_distribution": winner_stability,
        "elapsed_sec_avg": sum(elapsed_sec) / len(elapsed_sec) if elapsed_sec else 0.0,
        "elapsed_sec_std": pstdev(elapsed_sec) if len(elapsed_sec) > 1 else 0.0,
        "peak_memory_mb_avg": sum(peak_memory_mb) / len(peak_memory_mb) if peak_memory_mb else 0.0,
    }
    (args.output_root / "pilot_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
