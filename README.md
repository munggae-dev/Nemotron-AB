# Nemotron Personas Korea 마케팅 검증 도구

NVIDIA `Nemotron-Personas-Korea`를 기반으로 광고 카피 A/B를 20~50대(만 19~59세, 19세는 20s 버킷) 페르소나에 대해 검증하는 도구입니다.

## 주요 기능

- 19~59세 페르소나 필터 및 연령 버킷 분석(20s/30s/40s/50s, 19세는 20s에 포함)
- 벡터DB(Chroma) 기반 페르소나 검색, `retrieval_k_per_bucket`로 검색 후보 수 조절
- **카피·이미지 A/B**: 변형마다 카피만·이미지만·복합 가능(공개 URL 또는 `POST /jobs/assets` 업로드)
- 평가기 선택: `mock` 또는 로컬 Ollama LLM (**LangChain `ChatOllama`** 경로, 페르소나당 `job_tasks` 큐; 이미지 있을 때는 멀티모달 메시지)
- **Next.js(`apps/web`) + FastAPI(`apps/api`)** UI·API + SQLite 큐 + 워커
- 작업 완료/실패 알림 및 보고서(JSON) 조회

## 문서

- [프로젝트 개요](docs/project-overview.md) — 아키텍처(Web/API/워커/SQLite), 데이터 파이프라인, 주요 모듈 진입점
- [페르소나 벡터 DB 메타데이터](docs/vectordb-metadata.md) — Chroma 필드 목록·임베딩 문구 구성·`where`·API 연계·재빌드

## 환경 요구사항

- Python 3.11+
- Node.js 20+ (Next 로컬 개발 시)
- Ollama (실평가 시)
- CUDA GPU 권장(없어도 CPU 동작 가능)

## 빠른 시작 (권장: 웹 + API)

동일 SQLite DB(`app/app.sqlite3`)와 `outputs/`, `persona_db/`를 API·워커가 공유합니다.

```bash
source venv/bin/activate
# API 의존성(미설치 시)
pip install -r apps/api/requirements.txt
```

**터미널 1 — FastAPI**

프로젝트 **루트**에서 실행합니다(`apps.api.main` import 경로).

```bash
export APP_SQLITE_PATH="$PWD/app/app.sqlite3"
export CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8010
```

기본 API 포트는 **8010**입니다. `Address already in use` 면 `ss -tlnp | grep 8010` 으로 확인한 뒤, 다른 포트를 쓸 경우 `NEXT_PUBLIC_API_BASE_URL` 과 함께 맞추면 됩니다.

**터미널 2 — 워커** (`job_tasks` LLM 태스크 우선, 없으면 레거시 캠페인 단위 `run_validator`)

```bash
python -m app.worker_main --poll-interval-sec 2 --max-jobs-per-tick 1 --task-parallelism 2
```

`--task-parallelism`은 Ollama I/O 병렬용 스레드 수(1~8)입니다. 폼의 `eval_concurrency`와 비슷하게 맞추면 됩니다.

**터미널 3 — Next.js**

```bash
cd apps/web
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL 을 터미널 1의 API 포트와 동일하게 설정
npm install
npm run dev
```

브라우저에서 `http://localhost:3000` — 등록 / 큐 / 알림 / 보고서(작업 상세) 화면.

**브라우저 `ERR_CONNECTION_REFUSED`(포트 3000)** — Next 서버가 꺼진 상태입니다. `npm run dev` 가 떠 있는지 확인하세요.  
**폼 제출만 실패** — API가 안 떠 있거나 `.env.local` 의 URL이 실제 API 포트와 다릅니다. `curl http://127.0.0.1:8010/health` 로 확인합니다.

### 이미지 A/B 검증

- `POST /jobs` 본문에 선택 필드 `image_a`, `image_b`: `{ "type": "url", "value": "https://..." }` 또는 업로드 후 `{ "type": "asset_ref", "value": "staging/<파일명>" }`.
- 업로드: `POST /jobs/assets`(multipart 필드명 `file`) → 응답 `asset_ref`를 위 형태로 넣습니다. 작업 생성 시 파일은 `outputs/jobs/job_<id>/assets/`로 이동합니다.
- **실평가(`evaluator` ≠ `mock`)**일 때는 Ollama에 **비전(멀티모달) 가능 모델**을 지정해야 합니다. 예시 태그는 환경마다 다르며(`llava`, `moondream`, `qwen2-vl` 등), 텍스트 전용 모델은 호출이 실패할 수 있습니다.
- 업로드 크기 상한 **2MB**/파일, 포맷 png·jpeg·webp·gif. URL 이미지는 평가 시 서버가 다운로드합니다(사설 인증 URL은 실패 가능).
- 상세 화면·외부 연동용 이미지 URL: `GET /jobs/{id}/images/a`, `GET /jobs/{id}/images/b`(저장된 로컬 파일은 바로 응답, `type=url`이면 원본으로 리다이렉트).
- **`script/marketing_validator.py --evaluator ollama` 단일 텍스트 API 경로는 이미지 캠페인을 지원하지 않습니다.** 웹/`job_tasks` 워커 경로를 사용하세요.

### 환경 변수 (요약)

| 변수 | 설명 |
|------|------|
| `APP_SQLITE_PATH` | SQLite 절대 경로(API·워커 동일 권장). 미설정 시 `app/app.sqlite3` |
| `CORS_ORIGINS` | 쉼표 구분 Origin 목록. 기본 `http://localhost:3000` |
| `NEXT_PUBLIC_API_BASE_URL` | Next가 호출할 API 베이스 URL (미설정 시 코드 기본값 `http://127.0.0.1:8010`) |
| `PERSONA_RETRIEVE_BACKEND` | 비우면 기본(Chroma + SentenceTransformer). `langchain_chroma`면 LangChain Chroma 검색 경로 |
| `CHROMA_LC_DEVICE` | `cuda` 또는 기본 `cpu` — LangChain 임베딩 디바이스 |

## Docker Compose (선택)

이미지 빌드에 CPU용 PyTorch가 포함되어 첫 빌드가 무겁습니다. 로컬 `venv` 실행이 더 가벼운 경우가 많습니다.

```bash
docker compose up --build
```

- API: `http://localhost:8010`
- 웹: `http://localhost:3000` (브라우저가 호스트의 API를 부르므로 `NEXT_PUBLIC_API_BASE_URL` 기본값은 `http://localhost:8010`)
- 워커: 동일 이미지로 `app.worker_main` 실행, DB는 볼륨 `nemotron-data`의 `/data/app.sqlite3`

`persona_db`, `outputs`는 호스트 디렉터리를 마운트합니다. 사전에 `persona_db`를 구축해 두어야 검색·평가가 동작합니다.

## 데이터 준비

```bash
python script/download_data.py
```

## 단일/복수 캠페인 검증 (CLI)

샘플 입력(`script/sample_campaigns.json`) 기준 실행:

```bash
./venv/bin/python script/marketing_validator.py \
  --persona-file target_personas_20_59.jsonl \
  --campaign-file script/sample_campaigns.json \
  --profile small \
  --output-dir outputs
```

결과 파일:

- `outputs/<campaign_id>.partial.jsonl`
- `outputs/<campaign_id>.report.json`
- `outputs/<campaign_id>.report.md`

## 벡터DB 구축 (GPU 권장)

```bash
./venv/bin/python script/build_vectordb.py --device cuda
```

`target_personas_20_59.jsonl` 기준으로 **`marital_status`, `education_level`, `family_type`, `housing_type`, `military_status`** 를 메타데이터에 넣으며, 임베딩 텍스트에도 같은 맥락이 반영됩니다. 기존에 만든 `persona_db`에는 이 필드가 없을 수 있으니, 웹의 Nemotron 세부 필터를 쓰려면 **위 스크립트로 DB를 다시 빌드**하세요. 선택지 목록은 API `GET /meta/persona-filters` 또는 `app/persona_filter_schema.py`를 참고하면 됩니다.

기본 최적값(벤치 기준):

- `batch-size=4000`
- `encode-batch-size=512`
- `upsert-batch-size=5000`

## 벡터DB + Ollama 실평가

로컬 Ollama 모델(`gemma4:e4b-it-q4_K_M`) 사용 예시:

```bash
./venv/bin/python script/marketing_validator.py \
  --persona-source vectordb \
  --db-path persona_db \
  --collection-name marketing_personas \
  --campaign-file script/sample_campaigns.json \
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
./venv/bin/python script/benchmark_ollama.py \
  --concurrency-values 1,2,4,6 \
  --max-personas 16 \
  --retrieval-k-per-bucket 80
```

결과 요약:

- `outputs/benchmark_ollama/summary.json`

## 아키텍처 메모

- 작업 등록 시 `use_llm_task_queue=true`(기본)이면 Chroma로 페르소나를 확정한 뒤 `llm_score` 태스크가 `job_tasks`에 쌓입니다.
- 워커는 태스크가 없을 때만 `claim_next_pending_job_legacy_only`로 **태스크가 없는** `pending` job을 집어 레거시 `run_validator`(서브프로세스)를 실행합니다.
- `POST /jobs` 스키마는 `apps/api/main.py`의 Pydantic 모델과 동일하게 맞추었습니다.

## 파일럿 검증 (반복 안정성/성능 확인)

```bash
./venv/bin/python script/run_pilot.py \
  --persona-file target_personas_20_59.jsonl \
  --campaign-file script/sample_campaigns.json \
  --profile small \
  --runs 3
```

요약 결과:

- `outputs/pilot/pilot_summary.json`

## 프롬프트 출력 스키마

- `script/prompt_schema.json`

## 저장소 정책

- 대용량/로컬 산출물(`outputs/`, `persona_db/`, `target_personas_20_59.jsonl`, `venv/`)은 Git 추적에서 제외됩니다.
- 배포 스크립트/서비스 파일은 환경 의존성이 커서 저장소 추적 대상에서 제외됩니다.

## TODO

1. 기업 정보/브랜드 컨텍스트를 입력받아 평가 고도화
2. ~~텍스트 카피 외 이미지 기반 A/B 테스트 지원~~ (업로드·URL·멀티모달 평가·상세 썸네일 반영)
3. ~~LangChain 기반 파이프라인 구성~~ (1차 반영: `langchain_eval` + 선택적 `langchain_chroma` 검색)
4. ~~레거시 UI/UX 고도화~~ → Next.js UI로 완전 이전
5. 마케팅 실무 확장 기능 정의 및 단계적 추가
