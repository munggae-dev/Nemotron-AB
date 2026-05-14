# tests/

Nemotron-AB 의 단위/통합 테스트가 위치하는 디렉터리입니다. 1차 공개 시점에는 비어 있으며, 다음 영역부터 점진적으로 추가합니다.

## 우선순위

1. **점수 집계 로직** — `scripts/ab_validator.py` 의 `aggregate_results`, `weighted_sum`, `confidence_from_margin`.
2. **Persona where 변환** — `nemotron_ab/persona_where.py` 의 enum/문자열 정규화 케이스.
3. **API 입력 검증** — `backend/main.py` 의 Pydantic 모델(예: `image_a/image_b` URL/asset_ref 분기).
4. **워커 큐 상태 머신** — `nemotron_ab/db.py` 의 `claim_next_pending_task` 동시성 케이스(SQLite 트랜잭션).
5. **JSON 추출** — LLM 응답에서 JSON 객체 분리(`_extract_json_object`).

## 실행

```bash
pip install -e ".[dev]"
pytest -ra
```

## 작성 팁

- 외부 의존(Chroma, Ollama)이 필요한 케이스는 `pytest.mark.integration` 으로 분리해 기본 실행에서 제외하세요.
- 임시 SQLite 는 `tmp_path` 픽스처와 `APP_SQLITE_PATH` 환경 변수를 조합해 사용합니다.
