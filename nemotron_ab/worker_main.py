import argparse
import signal
import threading
import time
from pathlib import Path

from nemotron_ab import db
from nemotron_ab.queue_worker import run_worker_loop, run_worker_tick


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "nemotron_ab" / "app.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLite 작업 큐 백그라운드 워커")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--max-jobs-per-tick", type=int, default=1)
    parser.add_argument(
        "--task-parallelism",
        type=int,
        default=1,
        help="job_tasks 처리 시 동시 스레드 수(1~8). Ollama 병렬에 맞춰 eval_concurrency와 비슷하게 설정.",
    )
    parser.add_argument("--once", action="store_true", help="한 번만 실행하고 종료")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = db.get_conn(args.db_path)
    db.init_db(conn)
    print(
        f"[worker] started db={args.db_path} interval={args.poll_interval_sec}s "
        f"max_jobs_per_tick={args.max_jobs_per_tick} task_parallelism={args.task_parallelism}"
    )
    if args.once:
        processed = run_worker_tick(
            conn=conn,
            max_jobs=args.max_jobs_per_tick,
            task_parallelism=args.task_parallelism,
        )
        if processed > 0:
            print(f"[worker] processed={processed}")
        return

    stop_event = threading.Event()

    def _on_signal(signum, _frame) -> None:
        print(f"[worker] signal {signum} received, draining...", flush=True)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    def _on_processed(n: int) -> None:
        print(f"[worker] processed={n}", flush=True)

    run_worker_loop(
        conn=conn,
        task_parallelism=args.task_parallelism,
        poll_interval_sec=args.poll_interval_sec,
        stop_event=stop_event,
        on_processed=_on_processed,
    )


if __name__ == "__main__":
    main()
