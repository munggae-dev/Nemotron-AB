# 페르소나 벡터 DB(Chroma) 메타데이터

이 문서는 `script/build_vectordb.py`로 생성하는 **로컬 Chroma 컬렉션**(`persona_db`, 기본 이름 `marketing_personas`)에 저장되는 메타데이터와, 이를 사용하는 **API·검색 경로**를 정리합니다.

## 데이터 출처

- 원천: Hugging Face [`nvidia/Nemotron-Personas-Korea`](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea)
- 이 저장소 파이프라인: [`script/download_data.py`](../script/download_data.py)로 **만 19~59세**만 추출한 `target_personas_20_59.jsonl`
- 적재 스크립트: [`script/build_vectordb.py`](../script/build_vectordb.py)

## 컬렉션·식별자

| 항목 | 기본값 |
|------|--------|
| 저장 경로 | `persona_db/` (저장소 루트 기준, `.gitignore` 대상일 수 있음) |
| 컬렉션 이름 | `marketing_personas` |
| 문서 ID | 원본 레코드 `uuid` (없으면 `persona_{index}` 등 대체) |

## Chroma에 넣는 필드 요약

각 벡터(문서) 1건은 **임베딩용 텍스트**(`documents`)와 **필터용 메타데이터**(`metadatas`)를 가집니다.

### 메타데이터(`metadatas`) — 필드 정의

Chroma `where` 절에서 사용합니다. 타입은 Chroma 규약에 맞게 **문자열 또는 정수**로 통일되어 있습니다.

| 키 | 타입 | 설명 |
|----|------|------|
| `uuid` | string | Nemotron 레코드 식별자 |
| `age` | int | 만 나이 (19~59만 적재) |
| `age_bucket` | string | 분석 버킷: `20s`, `30s`, `40s`, `50s` (19세는 `20s`) |
| `sex` | string | `남자` / `여자` 등 데이터셋 값 |
| `occupation` | string | 직업 전체 문자열 (필터는 API에서 부분 일치 후처리) |
| `province` | string | 시·도 |
| `district` | string | 시·군·구 |
| `marital_status` | string | 혼인 상태 (Nemotron 라벨, 빈 문자열 가능) |
| `education_level` | string | 최종 학력 (Nemotron 라벨) |
| `family_type` | string | 가구 종류 (Nemotron 라벨) |
| `housing_type` | string | 주택 유형 (Nemotron 라벨) |
| `military_status` | string | 병역 상태 (Nemotron 라벨) |

**호환성:** `marital_status` 등 후반 메타 필드는 **벡터 DB를 해당 스크립트로 다시 빌드한 경우**에만 채워집니다. 예전 빌드 산출물에는 키가 없을 수 있으며, 그 상태에서 Nemotron 세부 필터를 쓰면 결과가 비거나 필터가 기대와 다를 수 있습니다.

### 임베딩 텍스트(`documents`)

`jhgan/ko-sroberta-multitask`로 임베딩되는 **한 줄 요약 문자열**은 대략 다음 요소를 ` | ` 로 이어 붙여 구성합니다(비어 있는 항목은 제외).

- 나이, 성별, 혼인, 학력, 가구, 주택, 병역, 직업, 거주(시도+시군구)
- `persona`, `professional_persona`, `hobbies_and_interests`, `career_goals_and_ambitions`

의미 검색 시 캠페인 맥락(제품·톤·카피 등)과 결합되어 쿼리 임베딩과 유사도 매칭됩니다.

## 애플리케이션에서의 사용

1. **기본 경로** ([`app/services/validator_runner.py`](../app/services/validator_runner.py)): Chroma `query` + `SentenceTransformer` 임베딩
2. **대체 경로** ([`app/chroma_langchain.py`](../app/chroma_langchain.py)): `PERSONA_RETRIEVE_BACKEND=langchain_chroma` 시 LangChain `Chroma` + 동일 임베딩 모델

### `where` 조건 생성

[`app/persona_where.py`](../app/persona_where.py)의 `chroma_where_and()`가 `persona_filter`를 `$and` 목록으로 변환합니다.

- 항상: `age` 구간 (`age_min` ~ `age_max`)
- 선택: `sex`, `province`, `district`
- 선택 (Nemotron 정합): `marital_status`, `education_level`, `family_type`, `housing_type`, `military_status` (값이 비어 있으면 조건에 넣지 않음)

### 직업(`occupation`) 필터

Chroma 메타만으로 부분 검색이 어려워, API의 `persona_filter.occupation_contains`는 **검색 결과를 받은 뒤** Python에서 `occupation` 문자열 **부분 일치**로 걸러 냅니다. 필터가 많을 때는 검색 상한(`n_results` / `k`)이 자동으로 커질 수 있습니다([`app/persona_filter_schema.py`](../app/persona_filter_schema.py)의 `retrieval_fanout_multiplier`).

## API·폼과의 대응

- 선택지·검증용 열거값: `GET /meta/persona-filters` ([`apps/api/main.py`](../apps/api/main.py)), 정의 원본 [`app/persona_filter_schema.py`](../app/persona_filter_schema.py)
- 지역 셀렉트: `GET /meta/regions` — [`app/regions.py`](../app/regions.py)

## 재빌드 절차

```bash
# 1) (선택) 최신 jsonl
./venv/bin/python script/download_data.py

# 2) 벡터 DB 생성/갱신
./venv/bin/python script/build_vectordb.py --device cuda
```

기존 `persona_db`를 덮어쓰므로, 백업이 필요하면 디렉터리를 복사해 둔 뒤 실행하세요.

## 관련 파일

| 파일 | 역할 |
|------|------|
| `script/build_vectordb.py` | jsonl → Chroma upsert, 메타·임베딩 구성 |
| `app/persona_where.py` | `persona_filter` → Chroma `where` |
| `app/persona_filter_schema.py` | Nemotron 라벨 집합, 검색 배수 |
| `app/services/validator_runner.py` | 기본 Chroma 검색 |
| `app/chroma_langchain.py` | LangChain Chroma 검색 |
