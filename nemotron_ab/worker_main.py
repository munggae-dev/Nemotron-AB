import argparse
import signal
import threading
from pathlib import Path
from typing import Union

from nemotron_ab import db
from nemotron_ab.db_engine import is_sqlite, resolve_database_url
from nemotron_ab.queue_worker import run_worker_loop, run_worker_tick


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A/B 평가 작업 큐 백그라운드 워커")
    # 미지정 시 DATABASE_URL → APP_SQLITE_PATH → 저장소 기본 경로 순으로 해석.
    # DATABASE_URL 이 postgresql 이면 PG, sqlite:/// 이면 SQLite 경로.
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="(레거시) SQLite 파일 경로. DATABASE_URL 이 우선합니다.",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="DB URL (sqlite:///… 또는 postgresql+psycopg://…). 환경변수 DATABASE_URL 보다 우선.",
    )
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


def _resolve_worker_target(args: argparse.Namespace) -> Union[Path, str]:
    """워커가 사용할 DB 타깃을 결정. CLI > DATABASE_URL > APP_SQLITE_PATH > 기본."""
    if args.database_url:
        return str(args.database_url).strip()
    if args.db_path is not None:
        return Path(args.db_path)
    url = resolve_database_url()
    if is_sqlite(url):
        # SQLite 는 그대로 URL 또는 Path 둘 다 지원하지만, 로그 가독성 위해 Path
        return db.default_sqlite_path()
    return url


def main() -> None:
    args = parse_args()
    target = _resolve_worker_target(args)
    conn = db.get_conn(target)
    db.init_db(conn)
    print(
        f"[worker] started db={target} interval={args.poll_interval_sec}s "
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
