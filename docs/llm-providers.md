# LLM 프로바이더

Nemotron-AB 는 **OpenAI 호환 엔드포인트** 라면 어떤 백엔드든 동일 코드 경로로
사용할 수 있습니다. 핵심 모듈은 `nemotron_ab/llm_provider.py` 입니다.

```
LLMConfig ──► make_chat_llm() ──► langchain_openai.ChatOpenAI
                                  │
                                  └── invoke(messages) ──► AIMessage
                                                            ├── content
                                                            └── usage_metadata
                                                                ├── input_tokens
                                                                ├── output_tokens
                                                                └── total_tokens
```

`extract_usage(response)` 가 `usage_metadata` / `response_metadata.token_usage` /
OpenAI 표준 `usage` 4가지 경로에서 토큰 수를 안전하게 추출합니다.

## 1. 설정 우선순위

| 출처 | 키 |
|---|---|
| 작업 payload | `llm_base_url` / `llm_model` |
| 환경변수 | `LLM_BASE_URL` / `LLM_MODEL` (`OPENAI_API_KEY` / `LLM_API_KEY`) |
| 기본값 | base_url 없음 (호출 시 에러), model 없음 |

`LLMConfig.repr` 은 API 키를 마스킹합니다(`api_key='sk-…'` 출력 차단).

```python
from nemotron_ab.llm_provider import resolve_llm_config

cfg = resolve_llm_config(base_url="http://localhost:11434/v1", model="gemma3:4b-it-q4_K_M")
print(cfg)  # LLMConfig(base_url='http://...', model='gemma3:...', api_key=***)
```

## 2. 엔드포인트별 사용 예시

### 2.1 Ollama (로컬)

`ollama serve` 후 — Ollama 의 OpenAI 호환 경로는 `/v1`.

```bash
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=gemma3:4b-it-q4_K_M
# 텍스트뿐 아니라 vision 모델도 그대로 동작 (gemma3-vision 등)
```

### 2.2 OpenAI 본사 API

```bash
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini
export OPENAI_API_KEY=sk-...   # 또는 LLM_API_KEY
```

### 2.3 기타 호환 엔드포인트

OpenAI 호환을 자처하는 서비스(vLLM, LM Studio, llama.cpp `server`, Azure OpenAI
proxy 등) 도 base_url 만 맞추면 동일하게 작동합니다.

## 3. JSON 강제 응답

`response_format_json=True` 일 때 LangChain `ChatOpenAI` 의 `response_format=
{"type":"json_object"}` 가 전달됩니다. 엔드포인트가 지원하지 않으면 무시되지만,
지원 시 비-JSON 잡음이 줄어 점수 파싱 안정성이 올라갑니다.

API 페이로드 / UI 의 *LLM 제공자* 카드에서 토글합니다. `prompt_profile=compact`
는 항상 JSON 모드를 강제합니다(아래 4번).

## 4. 프롬프트 프로파일

`nemotron_ab/prompt_profile.py` 가 `full` / `compact` 두 모드를 정의합니다.

| 프로파일 | 의도 | 페르소나 필드 | reason cap | JSON 강제 |
|---|---|---|---|---|
| `full` | 기본 — 페르소나 raw view | (전체) | 사용자 지정 (기본 80) | 사용자 토글 |
| `compact` | 토큰 절감 | `COMPACT_PERSONA_FIELDS` (핵심) | `COMPACT_REASON_CAP` (40) | 강제 ON |

`compact` 의 페르소나 핵심 필드는 코드(`COMPACT_PERSONA_FIELDS`) 에서 정의되며
연령·성별·직업·관심사 등 평가에 즉시 영향을 주는 항목 위주입니다.

또한 두 가지 길이 가드가 함께 적용됩니다.

- `max_persona_chars`: 페르소나 view 가 JSON 직렬화 시 이 길이를 넘으면
  `truncate_persona_view` 가 *긴 문자열 필드* 만 안전 절단 (dict 키 보존).
  기본 1500, 환경변수 `LLM_DEFAULT_MAX_PERSONA_CHARS` 로 변경.
- `max_context_chars`: `text_a + text_b + context` 누적 길이 서버측 가드.
  Pydantic 의 개별 `max_length` 와 별개로 *합계* 가드. 기본 4000, 환경변수
  `LLM_DEFAULT_MAX_CONTEXT_CHARS`.

```bash
# 예: 토큰 절감 모드 환경 기본값
export LLM_DEFAULT_PROMPT_PROFILE=compact
export LLM_DEFAULT_MAX_PERSONA_CHARS=900
export LLM_DEFAULT_MAX_CONTEXT_CHARS=2000
```

## 5. 토큰 사용량 흐름

```
ChatOpenAI.invoke() ──► AIMessage(usage_metadata=…)
                            │
        extract_usage(msg)──┘
                            │
                            ▼
       evaluate_persona_langchain → (result, usage)
                                        │
            job_tasks_worker → db.complete_task(... prompt/completion/total)
                                        │
                                        ▼
       /jobs/{id} 응답 ◄── db.job_token_totals(job_id)
              │
              └── 프론트 상세 화면의 "토큰 사용량" 풋터에 표시
```

엔드포인트에 따라 `usage_metadata` 가 비어있을 수 있습니다 — 그럴 땐 토큰 값
0 으로 저장되며, 작업은 정상 진행됩니다.

## 6. 디버깅 팁

- 응답이 JSON 이 아닐 때: `response_format_json=true` 또는 `prompt_profile=
  compact` 로 시도.
- 토큰이 0 으로 찍힐 때: 엔드포인트가 `usage` 를 반환하지 않음 — Ollama 일부
  버전은 `/v1` 응답에 `usage` 가 비어있음. Ollama 최신 버전 또는 다른 호환
  서버로 전환.
- 평가가 비싸게 도는 느낌: 먼저 `prompt_profile=compact` 적용, 그 다음
  `max_persona_chars` 축소, 마지막으로 `max_personas` 감소.

## 7. 관련 코드

| 파일 | 역할 |
|---|---|
| `nemotron_ab/llm_provider.py` | `LLMConfig`, `resolve_llm_config`, `make_chat_llm`, `extract_usage` |
| `nemotron_ab/langchain_eval.py` | `evaluate_persona_langchain` (멀티모달 + usage 반환) |
| `nemotron_ab/prompt_profile.py` | `resolve_prompt_profile`, `truncate_persona_view`, `VALID_PROFILES` |
| `nemotron_ab/job_tasks_worker.py` | LLM 호출 + 토큰 저장 + job 단위 집계 |
| `backend/schemas/jobs.py` | `JobCreate` Pydantic (입력 가드 + `prompt_profile` 검증) |
| `tests/unit/test_llm_provider.py` | `extract_usage` 4 케이스 + `LLMConfig` 마스킹 |
| `tests/unit/test_langchain_eval_tokens.py` | Fake ChatOpenAI 로 토큰 흐름 검증 |
| `tests/unit/test_prompt_profile.py` | 프로파일 해석 + 페르소나 view 절단 |
