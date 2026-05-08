# Nemotron Personas Korea 마케팅 검증 MVP

NVIDIA `Nemotron-Personas-Korea` 기반으로 광고 카피 A/B를 10~40대(10~49세) 페르소나에서 검증하는 경량 도구입니다.

## 포함 기능

- 연령 필터 고정: 10대/20대/30대/40대만 샘플링
- 하드웨어 대응 프로파일: `small`, `standard`
- 페르소나 소스 선택: 파일(`file`) 또는 벡터DB(`vectordb`)
- 평가 지표: `interest`, `click_intent`, `purchase_intent`, `trust`
- 최종 Winner 규칙: 가중 평균 점수 우선 + 동점 시 승률
- 평가기 선택: mock 또는 Ollama LLM
- 배치 처리, 재시도, 부분 저장(`*.partial.jsonl`)
- 출력: 연령대별 승률/점수, 전체 추천, 조건부 추천, 핵심 근거

## 실행 준비

페르소나 파일 생성:

```bash
python script/download_data.py
```

## 단일/복수 캠페인 검증

샘플 입력(`script/sample_campaigns.json`) 기준 실행:

```bash
./venv/bin/python script/marketing_validator.py \
  --persona-file target_personas_10_49.jsonl \
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

## Streamlit 앱 실행 (SQLite 큐)

Streamlit UI + SQLite 작업 큐 + 앱 내 알림으로 운영할 수 있습니다.

```bash
./venv/bin/streamlit run app/streamlit_app.py
```

구성 요소:

- 앱 엔트리: `app/streamlit_app.py`
- DB/큐 스키마: `app/db.py` (`app/app.sqlite3` 생성)
- 워커 코어: `app/queue_worker.py`
- 워커 프로세스 엔트리: `app/worker_main.py` (백그라운드 분리 실행)
- 검증 연동: `app/services/validator_runner.py`

주요 화면:

- 작업 등록: 카피 A/B, 캠페인 설명, 페르소나 필터(성별/연령/지역), 실행 옵션 입력
- 큐: `pending/running/completed/failed` 상태 확인
- 알림: 완료/실패 알림 확인 및 읽음 처리
- 보고서: 작업별 최종 winner, 연령대별 요약, 핵심 근거 조회

운영 메모:

- Python/라이브러리는 `venv` 기준 실행을 권장합니다.
- `evaluator=mock`은 빠른 검증용, `evaluator=ollama`는 실평가용입니다.
- 워커는 별도 프로세스로 상시 실행하세요:

```bash
./venv/bin/python -m app.worker_main --poll-interval-sec 2 --max-jobs-per-tick 1
```

- 단건 테스트 실행:

```bash
./venv/bin/python -m app.worker_main --once
```

## systemd 자동 실행 (선택)

워커를 서버 부팅 시 자동 실행하려면:

```bash
sudo cp deploy/systemd/marketing-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now marketing-worker.service
```

상태/로그 확인:

```bash
sudo systemctl status marketing-worker.service
journalctl -u marketing-worker.service -f
```

주의:

- 기본 유닛은 `User=renew`, `WorkingDirectory=/home/renew/workspace/nemotron-mini`로 설정되어 있습니다.
- 사용자명/경로가 다르면 `deploy/systemd/marketing-worker.service`를 먼저 수정한 뒤 복사하세요.

Streamlit UI도 자동 실행하려면:

```bash
sudo cp deploy/systemd/marketing-streamlit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now marketing-streamlit.service
```

UI 상태/로그 확인:

```bash
sudo systemctl status marketing-streamlit.service
journalctl -u marketing-streamlit.service -f
```

UI + 워커 함께 활성화:

```bash
sudo systemctl enable --now marketing-streamlit.service marketing-worker.service
```

## 파일럿 검증 (반복 안정성/성능 확인)

```bash
python script/run_pilot.py \
  --persona-file target_personas_10_49.jsonl \
  --campaign-file script/sample_campaigns.json \
  --profile small \
  --runs 3
```

요약 결과:

- `outputs/pilot/pilot_summary.json`

## 프롬프트 출력 스키마

- `script/prompt_schema.json`
