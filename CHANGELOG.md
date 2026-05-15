# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning aspires to [SemVer](https://semver.org/).

## [Unreleased]

본 섹션은 `origin/master` 이후 누적된 미릴리즈 변경입니다 — `pyproject.toml` 의
`version=0.1.0` 은 다음 릴리즈에서 갱신될 예정입니다.

### Added

- **Apple Silicon (MPS) 임베딩 가속** (`nemotron_ab/torch_device.py`)
  - `auto` 디바이스 우선순위: `cuda` > `mps` > `cpu`.
  - `scripts/build_vectordb.py`, `scripts/sanity_check_vectordb.py`, `scripts/ab_validator.py --retrieval-device`, API 워커 검색(`RETRIEVAL_DEVICE`), LangChain 경로(`CHROMA_LC_DEVICE`)에 반영.
  - FP16 `auto` 는 CUDA 전용(MPS/CPU 는 fp32로 Metal/CPU 가속만 사용).
- **LLM Provider 추상화** (`nemotron_ab/llm_provider.py`)
  - LangChain `ChatOpenAI` 기반의 단일 진입점. Ollama(/v1), OpenAI 등 OpenAI 호환 엔드포인트를 동일 코드 경로로 호출.
  - `LLMConfig` (env-only API 키 마스킹 repr), `resolve_llm_config()`, `make_chat_llm()`, `extract_usage()` 헬퍼.
  - `response_format_json` 으로 JSON 강제 응답 모드 지원.
- **토큰 사용량 추적**
  - `evaluate_persona_langchain()` 이 평가 결과와 함께 `usage_metadata` 를 반환.
  - `job_tasks.prompt_tokens / completion_tokens / total_tokens` 컬럼 추가 + 기존 DB 자동 마이그레이션.
  - `db.job_token_totals(job_id)` 로 job 단위 합계 집계. `/jobs/{id}` 응답과 UI 상세 화면에 노출.
- **프롬프트 프로파일 + 입력 가드** (Phase 2, `nemotron_ab/prompt_profile.py`)
  - `prompt_profile`: `full` (기본) / `compact` (핵심 페르소나 필드만 + reason cap + JSON 강제) — 토큰 절감.
  - `max_persona_chars`: 프롬프트 내 페르소나 JSON 직렬화 길이 캡, 초과 시 긴 문자열 필드만 안전 절단.
  - `max_context_chars`: `text_a + text_b + context` 누적 길이 서버측 가드.
  - 환경변수 기본값 오버라이드 (`LLM_DEFAULT_PROMPT_PROFILE` / `LLM_DEFAULT_MAX_PERSONA_CHARS` / `LLM_DEFAULT_MAX_CONTEXT_CHARS`).
- **DATABASE_URL + SQLAlchemy** (Phase 3.1)
  - `nemotron_ab/db_engine.py`: URL 우선순위 해석 (`DATABASE_URL > APP_SQLITE_PATH > 저장소 기본`), `make_engine()`.
  - `worker_main` 의 `--database-url` 인자 + SQLite/PG 자동 분기.
- **PostgreSQL 백엔드 지원** (Phase 3.2)
  - `DBConnection` wrapper (`db_engine.py`) — sqlite3.Connection 인터페이스(`execute`/`commit`/`executescript`/`row["col"]`/context manager/`lastrowid`) 를 SA Engine 의 raw_connection 위에서 PG/SQLite 양립으로 제공.
  - `?` placeholder → PG `%s` 자동 변환 (문자열 리터럴 보존), `INSERT … RETURNING id` 결과를 `cursor.lastrowid` 로 자동 노출.
  - `db.py` 의 SQL 을 dialect-agnostic 으로 통일: `CURRENT_TIMESTAMP`, `ON CONFLICT(job_id) DO UPDATE`, dialect 별 `BEGIN`/`BEGIN IMMEDIATE`, `BIGSERIAL`/`AUTOINCREMENT` 분기.
  - `db.py` 호출부 캡슐화 헬퍼 추가: `fetch_job_basic` / `fetch_job` / `transition_job_status` / `start_job_running`.
  - `docker compose --profile postgres` 로 PostgreSQL 컨테이너 옵션 제공.
  - `pip install -e .[postgres]` 로 psycopg 설치 후 `pytest -m needs_postgres` 통합 smoke 통과.
- **테스트 인프라**
  - `tests/conftest.py` — 격리 SQLite 픽스처 (`isolated_sqlite`/`fresh_conn`) + `FakeChatOpenAI` 팩토리.
  - `tests/unit/` 61개 단위 테스트 (DB 토큰/마이그레이션, JobCreate → payload, prompt/mock, FastAPI 라우트, `extract_usage` 4 케이스, `evaluate_persona_langchain` 토큰, `validator_runner` cmd 분기, `prompt_profile` 14, `db_engine` 16 — wrapper CRUD/RETURNING/executescript 포함).
  - `tests/integration/` E2E mock + 실제 Ollama LLM 토큰 적재 + PG 실연결 smoke.
  - pytest 마커: `integration` / `needs_ollama` / `needs_persona_db` / `needs_postgres`.

### Changed

- **A/B 평가 도메인 일반화**: `copy_a/b`, `product`, `category`, `tone`, `goal`, `description` → `text_a/b`, 단일 `context`. UI/CLI/문서 일관 갱신, 기존 jobs payload 호환 prefill 유지.
- **워커 LLM 클라이언트**: `ChatOllama` → `ChatOpenAI` (`llm_base_url`/`llm_model` payload 필드). 환경변수도 `LLM_BASE_URL`/`LLM_MODEL` 로 일반화.
- **검색 쿼리**: 마케팅 텍스트 우선 가중 → `context` + `text_a/b` 결합 (`scripts/ab_validator.py::build_retrieval_query`).
- **CLI 입력 스키마**: `scripts/ab_validator.py` 가 받는 JSON 의 필드 이름 일반화. 예제 `examples/sample_campaign_one.json` / `examples/sample_campaigns.json` 동시 갱신.
- **타입 힌트 현대화**: `ruff --fix` 로 PEP 585/604 문법(`tuple[X]` / `X | None`) 일괄 적용 — 22개 파일, 동작 변화 없음.

### Fixed

- **`KeyError: 'ollama_model'` 회귀** (`services/validator_runner.py`): evaluator 가 `ollama` 가 아닌 경우 모델 인자 미전달, `llm_model` 우선 폴백.
- **PG DDL 가시성**: `init_db` 이후 `_existing_columns` 가 SA inspector 대신 `information_schema.columns` 직접 조회로 변경 — 동일 트랜잭션 내 방금 만든 테이블도 보임.

### Migration notes

- 기존 `nemotron_ab/app.sqlite3` 는 자동 마이그레이션(`_migrate_add_token_columns`) 으로 토큰 컬럼 3개가 추가됩니다 — 별도 작업 없이 워커/백엔드 재시작만으로 동작.
- Postgres 로 전환할 경우 새 빈 DB 권장. 기존 SQLite 데이터의 PG 이전 스크립트는 본 릴리즈에는 포함되어 있지 않습니다.

---

## 0.1.0 (origin/master 시점)

초기 공개 준비 마일스톤 — 자세한 내용은 `git log` 의 `b47da34` 이전 커밋을 참고하세요.
주요 항목:

- 패키지 구조 정비: `app/`·`apps/web/`·`script/` → `nemotron_ab/`·`frontend/`·`scripts/`·`backend/`·`examples/`·`tests/`.
- 오픈소스 메타파일: `LICENSE`, `CONTRIBUTING.md`, `.github/` (CI·PR 템플릿), `.editorconfig`, `.env.example`.
- 벡터 DB 빌드 가속(`scripts/build_vectordb.py`): fp16, `max_seq_length=512`, `encode-batch-size=128`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments`. 67만건 ≈ 90분 안정 동작 (TITAN RTX 24GB).
- 검증·매니페스트 스크립트: `scripts/sanity_check_vectordb.py`, `scripts/build_manifest.py`, `persona_db/manifest.json`.
- HF Hub 사전 빌드 데이터셋 옵션: `renew-dev/nemotron-ab-persona-db-bge-m3` (CC-BY-4.0, 11.2 GB).
