# LAYA 텍스트 A/B 평가기

웹과 `JobCreate.evaluator`의 기본값은 `laya`입니다. Nemotron 페르소나 검색·SQLite 큐·기존 리포트 형식을 유지하면서 페르소나별 판단을 로컬 `convaiinnovations/laya-multilingual`로 실행합니다.
Ollama/OpenAI-호환 평가기는 `evaluator="openai"`로 계속 선택할 수 있습니다.

## 모델과 실행 환경

기본 의존성에 `laya==0.4.35`가 포함됩니다. PyTorch CUDA 빌드는 사용하는 GPU에 맞게 별도로 설치하세요. TITAN RTX에서 검증한 구성은 Python 3.11, PyTorch 2.14.0+cu130, CUDA FP16 autocast, eager/SDPA입니다.

```bash
python -m venv venv
source venv/bin/activate
pip install -e '.[dev]'
# CUDA GPU를 사용할 때 해당 장치에 맞는 PyTorch wheel 설치
# 검증한 TITAN RTX 예: pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu130
```

모델은 다음과 같이 고정된 리비전으로 다운로드합니다. 기존 `persona_db`와 `BAAI/bge-m3`는 별도로 준비해야 합니다.

```python
from huggingface_hub import snapshot_download

snapshot_download(
    "convaiinnovations/laya-multilingual",
    revision="92d22143468d8af669dc1a5a0480a2b21b4fe56e",
    local_dir="models/laya-multilingual",
    allow_patterns=["rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"],
)
```

`.env.example`을 복사하고 필요한 설정을 **API와 워커 양쪽에 export**한 뒤 기존 실행 명령을 사용합니다. `.env`는 Python 실행만으로 자동 로드되지 않습니다.

```bash
cp .env.example .env
set -a
source .env
set +a
# GPU 사용이 필수라면 지정. 자동 선택을 원하면 auto.
export LAYA_DEVICE=cuda
uvicorn backend.main:app --host 127.0.0.1 --port 8010
# 같은 환경을 로드한 다른 터미널에서:
python -m nemotron_ab.worker_main --poll-interval-sec 2 --task-parallelism 2
```

| 환경 변수 | 의미 |
| --- | --- |
| `LAYA_MODEL_PATH` | 모델 디렉터리. 기본 `models/laya-multilingual` |
| `LAYA_MODEL_REVISION` | 결과에 기록할 리비전. 다운로드한 모델과 맞춰 설정 |
| `LAYA_DEVICE` | `auto`(기본), `cuda`, `cpu` 등. 명시한 CUDA가 CPU로 폴백하면 거부 |
| `LAYA_MAX_LEN` | 입력 토큰 한도. 기본 8192 |

모델은 워커마다 한 번 로드해 재사용하고 호출은 잠금으로 직렬화합니다. `--task-parallelism=2`가 GPU 모델 두 개를 로드한다는 의미는 아닙니다. 페르소나 검색의 `RETRIEVAL_DEVICE`와 LAYA의 장치는 별개입니다.

## 점수와 근거

각 안을 독립적으로 입력하고 관심·클릭 의도·구매 의도·신뢰를 `choice` 질문으로 판단합니다. 각 질문을 긍정/부정 선택지 순서를 바꾸어 두 번 평가하고, 긍정 확률의 평균을 0~100으로 환산합니다. 기존 가중치 0.25/0.25/0.35/0.15를 적용해 최종 안을 정합니다. 반올림 후 같은 가중 점수이면 페르소나별 winner는 A입니다.

`purchase_intent`는 **돈을 지불하는 유료 구매·유료 구독 의향**으로 질문하며, 무료 체험만 시작하는 의향과 구분합니다. 결과의 방법 버전은 `binary-choice-probability-order-average-v2`입니다.

- `reason`은 점수의 숫자 요약입니다. 생성된 서술형 설명이 아닙니다.
- `confidence`는 기존 점수 차 지표이며 LAYA의 정답 확률을 뜻하지 않습니다.
- 원시 확률, 선택지 순서별 차이, 모델 리비전·장치·dtype은 partial JSONL에 기록합니다.
- Chroma 메타데이터 키를 정렬해 같은 페르소나의 필드 순서가 입력·점수를 바꾸지 않게 합니다.
- 입력이나 선택지가 토큰 한도에서 잘리면 실패 처리합니다.

점수는 합성 페르소나에 대한 모델 추정입니다. 실제 클릭률·구매율이 아니며, 이 한국어 과제에 대한 정확도·확률 보정 성능을 입증한 값도 아닙니다.

## 호환성과 제한

이 체크포인트는 텍스트용입니다. LAYA에 이미지를 넘기거나 레거시 큐 경로를 요청하면 API가 작업 생성 전에 400을 반환합니다. 이미지 평가에는 `openai`를 지정하세요. 레거시 CLI는 기존 평가기용입니다.
완료 리포트의 수동 종합 분석은 별도의 생성형 모델 호출입니다. 기본 A/B 점수 계산은 LAYA로 끝나며 종합 분석을 요구하지 않습니다.

기존 API 클라이언트가 평가기를 생략하면 이제 LAYA가 실행됩니다. 이미지나 기존 생성형 평가를 사용하는 클라이언트는 `evaluator="openai"`를 명시해야 합니다.

## 자료

- [LAYA 원본 코드와 모델 한계](https://github.com/NandhaKishorM/laya)
- [실측 비교 보고서](benchmarks/laya-vs-gemma-2026-11-17.md)
