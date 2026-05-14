# tests/

Nemotron-AB 의 단위/통합 테스트 모음입니다. Phase 1·2·3 검증 시나리오(일반화 A/B
스키마, LLM provider 추상화, 토큰 추적, 프롬프트 프로파일/캡, DB SA Core 호환
wrapper / Postgres 지원)를 재현 가능한 형태로 정리했습니다.

## 구성

```
tests/
├── conftest.py                       # 공통 픽스처 (격리 SQLite, Fake ChatOpenAI 팩토리)
├── unit/                             # 외부 의존 없는 단위 테스트
│   ├── test_db_token_columns.py      # job_tasks 토큰 컬럼·레거시 DB 마이그레이션·job_token_totals
│   ├── test_api_payload.py           # JobCreate → _payload_from_create (text_a/b, context, llm_*)
│   ├── test_prompt_and_mock.py       # build_prompt 일반화, evaluate_with_mock 결정성
│   ├── test_app_routes.py            # FastAPI 핵심 라우트 노출
│   ├── test_llm_provider.py          # extract_usage 4 케이스 + LLMConfig 마스킹/환경변수
│   ├── test_langchain_eval_tokens.py # evaluate_persona_langchain 토큰 추출 (ChatOpenAI 가짜 주입)
│   ├── test_validator_runner_cmd.py  # `ollama_model` KeyError 회귀 + cmd 조립 분기
│   ├── test_prompt_profile.py        # full/compact 프로파일 + persona view truncation
│   └── test_db_engine.py             # DATABASE_URL 우선순위 + DBConnection wrapper (CRUD/RETURNING/executescript)
└── integration/                      # uvicorn + worker + 외부 인프라가 필요한 E2E
    ├── conftest.py                   # 격리 스택 부팅, persona_db / Ollama 헬스체크
    ├── test_e2e_mock.py              # mock evaluator E2E (페르소나 8건, 토큰 0)
    ├── test_e2e_llm.py               # 실제 Ollama 호출, 토큰 적재·집계·항등식
    └── test_db_postgres.py           # PG 위 wrapper smoke (init_db / CRUD / ON CONFLICT / 토큰)
```

## 실행

```bash
pip install -e ".[dev]"

# 단위 테스트만 (기본)
pytest

# 통합까지 모두
pytest -m "integration or not integration"

# 통합만
pytest -m integration
```

기본 `addopts` 에 `-m "not integration"` 이 들어있어 `pytest` 만 실행하면
외부 의존 없는 단위 테스트만 동작합니다.

## 통합 테스트 사전 조건

| 마커 | 요구 사항 | 미충족 시 |
|---|---|---|
| `needs_persona_db` | `persona_db/` 가 빌드되어 있어야 함 (`scripts/build_vectordb.py`) | 자동 skip |
| `needs_ollama` | `LLM_BASE_URL` (기본 `http://localhost:11434/v1`) 응답 가능 | 자동 skip |
| `needs_postgres` | `DATABASE_URL=postgresql+psycopg://…` 가 설정되고 `psycopg` 설치 | 자동 skip |

환경 변수 오버라이드:

```bash
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=gemma4:e2b-it-q4_K_M
pytest -m integration
```

Postgres smoke:

```bash
docker compose --profile postgres up -d postgres
pip install -e .[postgres]
export DATABASE_URL='postgresql+psycopg://nemotron:nemotron@127.0.0.1:5432/nemotron'
pytest -m needs_postgres
```

## Frontend (참고)

프론트엔드 빌드 검증은 Next.js 영역이라 pytest 에 포함하지 않습니다.
별도로 다음을 실행합니다.

```bash
cd frontend && npm run build
```

## 작성 팁

- 외부 의존(Chroma, Ollama, 서브프로세스)이 필요한 케이스는
  `pytest.mark.integration` 으로 분리합니다.
- 임시 SQLite 는 `isolated_sqlite` / `fresh_conn` 픽스처를 사용해
  `APP_SQLITE_PATH` 가 자동 격리되도록 합니다.
- LLM 호출이 등장하는 단위 테스트는 `fake_chat_openai_factory` 픽스처로
  `langchain_openai.ChatOpenAI` 를 통째로 가짜 응답으로 교체합니다.
