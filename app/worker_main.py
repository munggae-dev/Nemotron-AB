import argparse
import time
from pathlib import Path

from app import db
from app.queue_worker import run_worker_tick


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "app" / "app.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLite 작업 큐 백그라운드 워커")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--max-jobs-per-tick", type=int, default=1)
    parser.add_argument("--once", action="store_true", help="한 번만 실행하고 종료")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = db.get_conn(args.db_path)
    db.init_db(conn)
    print(
        f"[worker] started db={args.db_path} interval={args.poll_interval_sec}s max_jobs_per_tick={args.max_jobs_per_tick}"
    )
    while True:
        processed = run_worker_tick(conn=conn, max_jobs=args.max_jobs_per_tick)
        if processed > 0:
            print(f"[worker] processed={processed}")
        if args.once:
            break
        time.sleep(args.poll_interval_sec)


if __name__ == "__main__":
    main()
