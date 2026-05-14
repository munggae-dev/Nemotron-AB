# Nemotron-AB

> NVIDIA `Nemotron-Personas-Korea` 기반 한국인 페르소나에 **단문(텍스트) 또는 이미지 A/B 변형**을 노출하고 LLM 으로 시뮬레이션 평가하는 오픈소스 도구입니다. 마케팅 카피뿐 아니라 공지 문구, UI 카피, 알림 메시지, 제품 설명, 이미지 등 짧은 콘텐츠 A/B 라면 어떤 것이든 적용할 수 있습니다.

**English short summary** — Nemotron-AB scores short-text and/or image A/B variants against synthetic Korean personas (ages 19–59) from NVIDIA's `Nemotron-Personas-Korea` dataset. It is domain-agnostic: marketing copy, in-product UI strings, notifications, internal announcements, image creatives — anything short fits. The stack ships a FastAPI backend, a Next.js dashboard, a SQLite-backed job queue, and a worker that calls a local Ollama LLM (with optional vision) through LangChain. Results are aggregated into JSON/Markdown reports per job.

## 주요 기능

- 19~59세 페르소나 필터·연령 버킷(20s/30s/40s/50s, 19세는 20s) 분석
- 벡터 DB(Chroma) 기반 페르소나 검색 (`retrieval_k_per_bucket` 로 후보 수 조절)
- 단문·이미지 A/B: 변형마다 텍스트만/이미지만/복합 가능 (공개 URL 또는 업로드)
- **OpenAI 호환 LLM 추상화**: `mock` 또는 OpenAI 호환 엔드포인트 (Ollama `/v1` · OpenAI 등) 를 동일 코드 경로로 사용. 멀티모달 지원
- **토큰 사용량 추적**: 평가마다 `prompt/completion/total` 토큰 수를 저장하고 job 단위로 집계하여 응답·UI 에 노출
- **프롬프트 프로파일** (`full` / `compact`) + 페르소나/컨텍스트 길이 가드 — 토큰 절감과 안정성
- **DB 백엔드 선택**: 기본 SQLite, `DATABASE_URL=postgresql+psycopg://…` 로 PostgreSQL 도 동일 코드 경로
- Next.js (`frontend`) + FastAPI (`backend`) UI/API + RDB 큐 + 워커
- 작업 완료·실패 알림과 보고서(JSON/Markdown) 자동 생성

## 문서

- [프로젝트 개요](docs/project-overview.md) — 아키텍처(Web/API/워커/RDB/LLM), 데이터 파이프라인, 모듈 진입점
- [데이터베이스](docs/database.md) — `DATABASE_URL` · SQLite ↔ PostgreSQL · SA wrapper · 마이그레이션
- [LLM 프로바이더](docs/llm-providers.md) — OpenAI 호환 엔드포인트 · 토큰 사용량 · 프롬프트 프로파일
- [페르소나 벡터 DB 메타데이터](docs/vectordb-metadata.md) — Chroma 필드·임베딩 문구·`where`·API 연계·재빌드
- [테스트 안내](tests/README.md) — 단위/통합/PG smoke 구조 및 pytest 마커
- [CONTRIBUTING](CONTRIBUTING.md) — 개발 환경, 코드 스타일, 커밋·PR 규약
- [데이터 디렉터리](data/README.md) — 대용량 데이터셋·벡터 DB 생성 가이드
- [CHANGELOG](CHANGELOG.md) — 변경 이력

## 환경 요구사항

- Python 3.11+
- Node.js 20+ (Next 로컬 개발 시)
- LLM: 로컬 Ollama 또는 OpenAI 호환 엔드포인트 (실평가 시)
- (옵션) PostgreSQL 14+ — `DATABASE_URL` 로 전환 시
- CUDA GPU 권장(없어도 CPU 동작 가능)

## 빠른 시작 (권장: 웹 + API)

동일 SQLite DB(`nemotron_ab/app.sqlite3`)와 `outputs/`, `persona_db/` 를 API·워커가 공유합니다.

```bash
python -m venv venv
source venv/bin/activate
pip install -e .          # 또는 pip install -r backend/requirements.txt
```

**터미널 1 — FastAPI**

프로젝트 **루트**에서 실행합니다(`backend.main` import 경로).

```bash
export APP_SQLITE_PATH="$PWD/nemotron_ab/app.sqlite3"
export CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8010
```

기본 API 포트는 **8010**입니다. `Address already in use` 면 `ss -tlnp | grep 8010` 으로 확인하세요. Next는 기본적으로 **브라우저가 `/_nemotron_api`(동일 호스트)** 로만 호출하고 서버가 FastAPI로 넘깁니다. API를 다른 포트에서 띄운 경우에는 `API_INTERNAL_URL` 과 맞추거나, 직접 붙이려면 `NEXT_PUBLIC_API_BASE_URL` 을 명시하세요.

**터미널 2 — 워커** (`job_tasks` LLM 태스크 우선, 없으면 레거시 job 단위 `run_validator`)

```bash
python -m nemotron_ab.worker_main --poll-interval-sec 2 --max-jobs-per-tick 1 --task-parallelism 2
```

`--task-parallelism`은 Ollama I/O 병렬용 스레드 수(1~8)입니다. 폼의 `eval_concurrency`와 비슷하게 맞추면 됩니다.

**터미널 3 — Next.js**

```bash
cd frontend
cp .env.example .env.local   # 기본은 설정 불필요(프록시 사용). `.env.local`에 옛 `NEXT_PUBLIC_API_BASE_URL=8010`만 있으면 포트포워딩 시 오류가 날 수 있으니 해당 줄을 지우세요.
npm ci
npm run dev
```

브라우저에서 `http://localhost:3000` — 등록 / 큐 / 알림 / 보고서(작업 상세) 화면.

**브라우저 `ERR_CONNECTION_REFUSED`(포트 3000)** — Next 서버가 꺼진 상태입니다. `npm run dev` 가 떠 있는지 확인하세요.  
**폼 제출만 실패·`8010 ERR_CONNECTION_RESET`** — `.env.local`에 **`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010` 이 남아 있으면**, 브라우저(PC의 8010)로 직접 붙습니다. 원격 작업만 포워딩한 경우 **그 줄을 삭제**(기본 프록시 사용)하고 `npm run dev` 재시작. API가 같은 머신의 다른 포트면 `API_INTERNAL_URL` 로 맞춥니다.

#### 포트포워딩 / 원격 개발 (SSH 등)

- 기본 설정이면 브라우저는 **`http(s)://(포워딩한 호스트):3000/_nemotron_api/...`** 만 사용합니다. **3000만 열어도 됩니다.**
- **주소창이 `localhost` vs `127.0.0.1`** → CORS가 달라질 수 있습니다. API 기본 `CORS_ORIGINS`는 둘 다 허용합니다.
- Next는 **`0.0.0.0:3000`** 에 바인드됩니다. API는 `--host 0.0.0.0`(README 예시와 동일)을 권장합니다.

### 이미지 A/B 검증

- `POST /jobs` 본문에 선택 필드 `image_a`, `image_b`: `{ "type": "url", "value": "https://..." }` 또는 업로드 후 `{ "type": "asset_ref", "value": "staging/<파일명>" }`.
- 업로드: `POST /jobs/assets`(multipart 필드명 `file`) → 응답 `asset_ref`를 위 형태로 넣습니다. 작업 생성 시 파일은 `outputs/jobs/job_<id>/assets/`로 이동합니다.
- **실평가(`evaluator` ≠ `mock`)**일 때는 Ollama에 **비전(멀티모달) 가능 모델**을 지정해야 합니다. 예시 태그는 환경마다 다르며(`llava`, `moondream`, `qwen2-vl` 등), 텍스트 전용 모델은 호출이 실패할 수 있습니다.
- 업로드 크기 상한 **2MB**/파일, 포맷 png·jpeg·webp·gif. URL 이미지는 평가 시 서버가 다운로드합니다(사설 인증 URL은 실패 가능).
- 상세 화면·외부 연동용 이미지 URL: `GET /jobs/{id}/images/a`, `GET /jobs/{id}/images/b`(저장된 로컬 파일은 바로 응답, `type=url`이면 원본으로 리다이렉트).
- **`scripts/ab_validator.py --evaluator ollama` 단일 텍스트 API 경로는 이미지 입력을 지원하지 않습니다.** 웹/`job_tasks` 워커 경로를 사용하세요.

### 환경 변수 (요약)

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | SQLAlchemy DB URL. `sqlite:///{abs}` 또는 `postgresql+psycopg://user:pw@host:port/db`. 설정 시 `APP_SQLITE_PATH` 보다 우선합니다. |
| `APP_SQLITE_PATH` | SQLite 절대 경로(API·워커 동일 권장). `DATABASE_URL` 미설정 시에만 사용. 미설정 시 `nemotron_ab/app.sqlite3` |
| `CORS_ORIGINS` | 쉼표 구분 Origin 목록. 미설정 시 `localhost:3000`·`127.0.0.1:3000` |
| `NEXT_PUBLIC_API_BASE_URL` | **설정 시** 브라우저가 이 URL로 직접 호출(프록시 미사용). 비우면 `/_nemotron_api` 프록시 |
| `API_INTERNAL_URL` | Next 서버가 FastAPI로 붙을 URL(SSR·rewrite 목적지). 기본 `http://127.0.0.1:8010` |
| `PERSONA_RETRIEVE_BACKEND` | 비우면 기본(Chroma + SentenceTransformer). `langchain_chroma`면 LangChain Chroma 검색 경로 |
| `EMBED_MODEL_NAME` | 임베딩 모델(Sentence-Transformers/HF 호환). 미지정 시 기본값 `BAAI/bge-m3` (MIT, 1024d). 변경 시 `persona_db` 재빌드 필요 |
| `CHROMA_LC_DEVICE` | `cuda` 또는 기본 `cpu` — LangChain 임베딩 디바이스 |
| `NEMOTRON_AB_PY` | 레거시 서브프로세스용 Python 실행 경로 오버라이드(기본 `./venv/bin/python` 또는 현재 인터프리터) |

## Docker Compose (선택)

이미지 빌드에 CPU용 PyTorch가 포함되어 첫 빌드가 무겁습니다. 로컬 `venv` 실행이 더 가벼운 경우가 많습니다.

```bash
docker compose up --build
```

- API: `http://localhost:8010`
- 웹: `http://localhost:3000` (브라우저→`/_nemotron_api`→ Compose 네트워크의 API; 별도 `NEXT_PUBLIC_API_BASE_URL` 불필요)
- 워커: 동일 이미지로 `nemotron_ab.worker_main` 실행, DB는 볼륨 `nemotron-data`의 `/data/app.sqlite3`

`persona_db`, `outputs`는 호스트 디렉터리를 마운트합니다. 사전에 `persona_db`를 구축해 두어야 검색·평가가 동작합니다.

### Postgres 백엔드 (옵션, Phase 3.2+)

SQLite 대신 PostgreSQL 을 사용하려면 `DATABASE_URL` 만 지정하면 됩니다 — 코드 경로는 동일하게 작동합니다(`db.py` 가 SA Core 호환 wrapper 위에서 dialect-agnostic SQL 을 사용).

```bash
# 1) Postgres 컨테이너 띄우기 (compose 프로파일 활용)
docker compose --profile postgres up -d postgres

# 2) 의존성 설치 (psycopg)
pip install -e .[postgres]

# 3) DATABASE_URL 설정 (API/워커가 모두 따라감)
export DATABASE_URL='postgresql+psycopg://nemotron:nemotron@127.0.0.1:5432/nemotron'

# 4) 평소처럼 API/워커 실행
uvicorn backend.main:app --reload --port 8010 &
python -m nemotron_ab.worker_main --poll-interval-sec 2 --task-parallelism 2 &
```

호환 검증: `pytest -m needs_postgres` (DATABASE_URL 이 PG 이고 psycopg 가 설치된 경우에만 동작).

## 데이터 준비

```bash
python scripts/download_data.py
```

자세한 절차는 [data/README.md](data/README.md) 참고.

## 단일/복수 A/B 평가 (CLI)

샘플 입력(`examples/sample_campaigns.json`) 기준 실행:

```bash
./venv/bin/python scripts/ab_validator.py \
  --persona-file target_personas_20_59.jsonl \
  --campaign-file examples/sample_campaigns.json \
  --profile small \
  --output-dir outputs
```

입력 JSON 스키마:

```json
[
  {
    "id": "<유일 ID>",
    "context": "무엇을 비교하는지, 어떤 청중·상황에 쓰이는지 자유 서술",
    "text_a": "안 A 의 단문",
    "text_b": "안 B 의 단문",
    "image_a": { "type": "url", "value": "https://..." },
    "image_b": { "type": "url", "value": "https://..." }
  }
]
```

`image_a`/`image_b` 는 선택입니다. `text_*` 와 `image_*` 중 변형마다 최소 하나가 있으면 됩니다.

결과 파일:

- `outputs/<id>.partial.jsonl`
- `outputs/<id>.report.json`
- `outputs/<id>.report.md`

## 벡터DB 준비

두 가지 옵션이 있습니다. 빠르게 시작하려면 **옵션 B** 권장.

### 옵션 A — 직접 빌드 (GPU 권장)

```bash
./venv/bin/python scripts/build_vectordb.py --device cuda
```

`target_personas_20_59.jsonl` 기준으로 **`marital_status`, `education_level`, `family_type`, `housing_type`, `military_status`** 를 메타데이터에 넣으며, 임베딩 텍스트에도 같은 맥락이 반영됩니다. 기존에 만든 `persona_db`에는 이 필드가 없을 수 있으니, 웹의 Nemotron 세부 필터를 쓰려면 **위 스크립트로 DB를 다시 빌드**하세요. 선택지 목록은 API `GET /meta/persona-filters` 또는 `nemotron_ab/persona_filter_schema.py` 를 참고하면 됩니다.

기본 최적값(TITAN RTX 24GB 벤치 기준, fp16 + max_seq_length 512):

- `batch-size=4000`
- `encode-batch-size=128` (VRAM 여유 있으면 256까지)
- `upsert-batch-size=5000`
- `max-seq-length=512` (데이터 실측 토큰수 max 507 / p99 462 → 잘림 없음)
- `--fp16 auto` (CUDA 면 자동 ON)

전체 67만 건 기준 약 **100~150 rows/s, 90~120분** 소요. 중단되면 동일 명령에 `--resume` 만 붙이면 이어서 진행합니다.

빌드 후 검증·매니페스트 생성:

```bash
./venv/bin/python scripts/sanity_check_vectordb.py        # 카운트·분포·필터·의미 검색 sanity
./venv/bin/python scripts/build_manifest.py               # persona_db/manifest.json (SHA-256 포함)
```

### 옵션 B — 미리 빌드된 DB 받기 (~11.2GB, ~2분)

본 프로젝트에서 빌드해 HF Hub 에 올려 둔 산출물을 그대로 가져다 쓸 수 있습니다.

- Hub: [`renew-dev/nemotron-ab-persona-db-bge-m3`](https://huggingface.co/datasets/renew-dev/nemotron-ab-persona-db-bge-m3)
- 임베딩: `BAAI/bge-m3` (1024d, normalize, fp16 추론, `max_seq_length=512`)
- 적재 건수: **669,558** (age 19~59)
- 라이선스: **CC-BY-4.0** (원본 `nvidia/Nemotron-Personas-Korea` 와 동일)

```bash
./venv/bin/hf download renew-dev/nemotron-ab-persona-db-bge-m3 \
  --repo-type dataset --local-dir ./persona_db
```

`persona_db/manifest.json` 에 모든 파일의 SHA-256 이 들어있어 무결성 검증이 가능하고, 임베딩 텍스트 스키마/모델/차원 등 재현에 필요한 정보가 박혀 있습니다. **검색 시에는 동일 모델·동일 정규화·동일 텍스트 스키마를 써야** 의미가 보존됩니다.

## 벡터DB + Ollama 실평가

로컬 Ollama 모델(`gemma4:e4b-it-q4_K_M`) 사용 예시:

```bash
./venv/bin/python scripts/ab_validator.py \
  --persona-source vectordb \
  --db-path persona_db \
  --collection-name marketing_personas \
  --campaign-file examples/sample_campaigns.json \
  --profile small \
  --evaluator ollama \
  --ollama-model gemma4:e4b-it-q4_K_M \
  --retrieval-device cuda \
  --eval-concurrency 2 \
  --max-personas 24 \
  --retrieval-k-per-bucket 80 \
  --output-dir outputs/ollama_run
```

권장 기본값:

- `eval-concurrency=2` (현재 머신 벤치 최적)
- `max-personas=0`이면 profile 기본값 사용(`small=40`, `standard=80`)
- 빠른 반복 실험: `max-personas=12~24`
- 품질 우선 실험: `max-personas=40+`

## Ollama 동시성 벤치마크

```bash
./venv/bin/python scripts/benchmark_ollama.py \
  --concurrency-values 1,2,4,6 \
  --max-personas 16 \
  --retrieval-k-per-bucket 80
```

결과 요약:

- `outputs/benchmark_ollama/summary.json`

## 아키텍처 메모

- 작업 등록 시 `use_llm_task_queue=true`(기본)이면 Chroma로 페르소나를 확정한 뒤 `llm_score` 태스크가 `job_tasks`에 쌓입니다.
- 워커는 태스크가 없을 때만 `claim_next_pending_job_legacy_only`로 **태스크가 없는** `pending` job을 집어 레거시 `run_validator`(서브프로세스)를 실행합니다.
- `POST /jobs` 본문은 `backend/main.py` 의 Pydantic `JobCreate`에 그대로 매핑됩니다. 최소 필드는 `title`, `text_a`/`text_b`(또는 `image_a`/`image_b`), `context`, `persona_filter`.

## 파일럿 검증 (반복 안정성/성능 확인)

```bash
./venv/bin/python scripts/run_pilot.py \
  --persona-file target_personas_20_59.jsonl \
  --campaign-file examples/sample_campaigns.json \
  --profile small \
  --runs 3
```

요약 결과:

- `outputs/pilot/pilot_summary.json`

## 프롬프트 출력 스키마

- `examples/prompt_schema.json`

## 저장소 정책

- 대용량/로컬 산출물(`outputs/`, `persona_db/`, `target_personas_20_59.jsonl`, `venv/`, `data/`)은 Git 추적에서 제외됩니다.
- 배포 스크립트/서비스 파일은 환경 의존성이 커서 저장소 추적 대상에서 제외됩니다.

## 라이선스 / 외부 의존물

- 본 저장소 코드: 첫 정식 릴리스 전에 확정 — [LICENSE](LICENSE) 참고.
- 원천 데이터셋: [`nvidia/Nemotron-Personas-Korea`](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) — **CC-BY-4.0**.
- 기본 임베딩 모델: [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) — **MIT**. 가중치는 런타임에 Hugging Face에서 다운로드되며 본 저장소에 포함되지 않습니다.
- 기본 LLM 평가기: 사용자의 로컬 [Ollama](https://ollama.com/) 모델(예: `gemma`, `llava`). 각 모델의 라이선스는 별도 확인 필요.

## 로드맵

1. 사용자 정의 평가 지표(metrics) 지원 — 기본 4지표(`interest`/`click_intent`/`purchase_intent`/`trust`) 외 자유 정의
2. ~~텍스트 외 이미지 기반 A/B 테스트 지원~~ (업로드·URL·멀티모달 평가·상세 썸네일 반영)
3. ~~LangChain 기반 파이프라인 구성~~ (1차 반영: `langchain_eval` + 선택적 `langchain_chroma` 검색)
4. ~~레거시 UI/UX 고도화~~ → Next.js UI로 완전 이전
5. ~~단위/통합 테스트 본격 추가~~ (단위 61건 + 통합 3건 + `needs_postgres` smoke — [tests/](tests/) 참고)
6. 평가 도메인별 프롬프트 프리셋(마케팅, 공지, UI 카피 등) 단계적 제공
7. Apple Silicon (MPS) 임베딩 가속 — `CHROMA_LC_DEVICE` 와 `scripts/build_vectordb.py --device` 에 `mps` 분기 추가, `auto` 기본값을 `cuda > mps > cpu` 우선순위로. M-series 맥에서 임베딩 4~8배 가속 예상.
8. SQLite ↔ PostgreSQL 데이터 이전 스크립트(`scripts/migrate_sqlite_to_postgres.py`) — 운영 데이터 보존 이전 자동화 (현재는 새 DB 권장).
