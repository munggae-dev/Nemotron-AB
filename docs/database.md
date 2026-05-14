# 데이터베이스 (RDB)

Nemotron-AB 의 RDB 계층은 **SQLite** 와 **PostgreSQL** 을 *동일 코드 경로* 로
지원합니다. 핵심은 두 가지입니다.

1. `nemotron_ab/db_engine.py` 의 `DBConnection` — `sqlite3.Connection` 호환
   인터페이스를 SQLAlchemy Engine 의 raw DBAPI 위에 입혀 PG/SQLite 양립.
2. `nemotron_ab/db.py` 의 SQL — `CURRENT_TIMESTAMP`, `ON CONFLICT`, dialect 별
   `BIGSERIAL`/`AUTOINCREMENT` 분기 등 dialect-agnostic 표현.

## 1. 연결 설정

DB 위치는 다음 우선순위로 결정됩니다.

1. `DATABASE_URL` 환경변수 — `sqlite:///{abs}` 또는 `postgresql+psycopg://user:pw@host:port/db`
2. `APP_SQLITE_PATH` — SQLite 파일 절대 경로 (1번이 비어 있을 때만)
3. 저장소 기본 — `./nemotron_ab/app.sqlite3`

```bash
# 기본 SQLite (그냥 실행)
uvicorn backend.main:app --reload --port 8010

# 명시적 SQLite 경로
export APP_SQLITE_PATH="$PWD/nemotron_ab/app.sqlite3"

# PostgreSQL
export DATABASE_URL='postgresql+psycopg://nemotron:nemotron@127.0.0.1:5432/nemotron'
pip install -e ".[postgres]"   # psycopg[binary] 설치
```

워커도 같은 변수를 따릅니다. CLI 인자로 명시적 오버라이드도 가능합니다.

```bash
python -m nemotron_ab.worker_main \
  --database-url 'postgresql+psycopg://...' \
  --poll-interval-sec 2 --task-parallelism 2
```

## 2. 스키마

| 테이블 | 용도 |
|---|---|
| `jobs` | 작업 등록·상태(`pending`/`preparing`/`running`/`completed`/`failed`)·payload(JSON) |
| `job_results` | 완료 시 리포트 경로·partial JSONL 경로·요약(JSON, 토큰 합계 포함) |
| `notifications` | UI 알림 |
| `job_tasks` | LLM 세분화 큐 — 페르소나별 `llm_score` 태스크. `prompt/completion/total_tokens` 컬럼으로 사용량 누적 |

`init_db()` 은 호출 시점의 dialect 에 맞게 DDL 을 자동 분기합니다.

- SQLite: `id INTEGER PRIMARY KEY AUTOINCREMENT`
- Postgres: `id BIGSERIAL PRIMARY KEY` (PG 10+ IDENTITY 대신 호환성 우선)

## 3. 마이그레이션 (멱등)

기존 SQLite 의 `job_tasks` 에 토큰 컬럼 3개가 없으면 `_migrate_add_token_columns`
가 `ALTER TABLE … ADD COLUMN` 으로 자동 추가합니다.

- 컬럼 존재 여부 조회는 dialect 별 분기:
  - SQLite: `PRAGMA table_info(job_tasks)`
  - Postgres: `information_schema.columns` 직접 조회 (동일 트랜잭션 내 가시성 보장)

별도 마이그레이션 도구(Alembic 등) 가 도입되기 전까지는 *DDL 변경 시* 이 함수에
추가 컬럼 보강 로직을 더하는 방식을 따릅니다.

## 4. SA Core 호환 wrapper

```python
from nemotron_ab.db_engine import DBConnection, make_engine

engine = make_engine("postgresql+psycopg://user:pw@host/db")
conn = DBConnection(engine)
conn.executescript("""CREATE TABLE IF NOT EXISTS t(id INT, name TEXT);""")
conn.commit()
cur = conn.execute("INSERT INTO t(id, name) VALUES(?, ?) RETURNING id", (1, "a"))
print(cur.lastrowid)   # 1 — RETURNING 결과를 자동 노출
row = conn.execute("SELECT * FROM t WHERE id=?", (1,)).fetchone()
print(row["name"], row[0])  # row["col"], row[int] 모두 지원
```

특징:

- `?` placeholder 가 PG 경로에선 `%s` 로 자동 변환 (문자열 리터럴 `'…?…'` 안의
  `?` 는 보존).
- `INSERT … RETURNING id` 결과를 첫 번째 fetch 로 소비하고 `cursor.lastrowid`
  에 저장 (PG/SQLite 동일 인터페이스).
- `executescript` 는 SQLite 는 native `executescript`, PG 는 세미콜론 기준
  statement 분할 후 driver 직접 실행.
- `with DBConnection(engine) as conn: ...` context manager 지원 — sqlite3 와
  동일 의미(성공 시 commit, 실패 시 rollback, 종료 시 닫히지 않음).

## 5. 호출부에서 보는 인터페이스

`db.py` 의 모든 헬퍼는 sqlite3.Connection 또는 DBConnection 을 `conn` 으로
받습니다 (별칭 `ConnectionLike`). 자주 쓰는 함수:

| 함수 | 의미 |
|---|---|
| `enqueue_job(conn, title, payload, status=…)` | 작업 등록 → `id` 반환 |
| `fetch_job(conn, id)` | 단일 job 전체 조회 |
| `fetch_job_basic(conn, id)` | id/title/payload_json 만 (이미지 등) |
| `transition_job_status(conn, id, from_status=…, to_status=…)` | 조건부 상태 전이 |
| `start_job_running(conn, id)` | `running` 으로 표시 + `started_at` 기록 |
| `claim_next_pending_task(conn)` | LLM 큐에서 1건 선점 (`BEGIN IMMEDIATE` / `BEGIN`) |
| `complete_task(conn, id, prompt_tokens=…, completion_tokens=…, total_tokens=…)` | 완료 표시 + 토큰 저장 |
| `job_token_totals(conn, id)` | `prompt/completion/total/task_count` 집계 |
| `complete_job(conn, id, report_json_path, partial_jsonl_path, summary)` | jobs+job_results 멱등 갱신 (`ON CONFLICT(job_id) DO UPDATE`) |

## 6. PostgreSQL 운용

### 6.1 컨테이너로 빠르게 부팅

`docker-compose.yml` 의 `postgres` 프로파일을 사용합니다.

```bash
docker compose --profile postgres up -d postgres
docker compose exec -T postgres pg_isready -U nemotron -d nemotron
```

기본 자격증명: `nemotron / nemotron`, DB `nemotron`, 호스트 포트 `5432`.

### 6.2 호환 smoke

```bash
pip install -e ".[postgres]"
export DATABASE_URL='postgresql+psycopg://nemotron:nemotron@127.0.0.1:5432/nemotron'
pytest -m needs_postgres -v
```

검증 항목: `init_db` (BIGSERIAL DDL) → 토큰 누적 → `transition_job_status` →
`complete_job` 의 `ON CONFLICT` 멱등성.

### 6.3 SQLite ↔ PostgreSQL 데이터 이전

본 릴리즈에는 *마이그레이션 스크립트가 포함되어 있지 않습니다*. 운영 데이터
이전이 필요하면 `pgloader` 또는 다음 방식을 추천합니다.

1. SQLite 측: `.dump` 로 스키마/데이터 SQL 추출
2. 수동 변환: `AUTOINCREMENT` → `BIGSERIAL`, BOOL/TIMESTAMP 표현
3. PG 측: `psql -f` 로 적재
4. 또는 새 빈 PG 로 시작하고 처음부터 재실행 (가장 안전)

## 7. 트랜잭션·동시성 메모

- `claim_next_pending_task` 는 SQLite 에선 `BEGIN IMMEDIATE` 로 *쓰기 락*을
  먼저 잡아 race 를 방지합니다. PG 에선 `BEGIN` (기본 `READ COMMITTED`) — 향후
  필요 시 `SELECT … FOR UPDATE SKIP LOCKED` 도 검토 가능.
- 워커 스레드 풀이 다중 커넥션을 사용할 때 `queue_worker._resolve_worker_target`
  이 SQLite Path 또는 SA URL 을 정확히 전달하므로 새 연결도 동일 백엔드에
  붙습니다.

## 8. 관련 코드

| 파일 | 역할 |
|---|---|
| `nemotron_ab/db_engine.py` | URL 해석 / SA Engine / `DBConnection` wrapper |
| `nemotron_ab/db.py` | dialect-agnostic 스키마·CRUD 헬퍼 |
| `nemotron_ab/queue_worker.py` | 스레드 풀에서 새 커넥션 생성 (sqlite Path / SA URL) |
| `nemotron_ab/worker_main.py` | `--db-path` / `--database-url` / env 우선순위 |
| `tests/unit/test_db_engine.py` | wrapper 단위 테스트 (CRUD/RETURNING/executescript/qmark) |
| `tests/integration/test_db_postgres.py` | 실연결 smoke (`needs_postgres` 마커) |
