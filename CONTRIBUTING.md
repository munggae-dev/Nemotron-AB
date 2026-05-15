# Contributing to Nemotron-AB

기여해 주셔서 감사합니다. 본 문서는 개발 환경 구성, 코드 스타일, 커밋·PR 절차를 정리합니다.

## 개발 환경

### Python (백엔드/워커/CLI)

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"        # 코어 + ruff/black/pytest
# GPU 사용 시
pip install -e ".[dev,gpu]"
```

### Node.js (프론트엔드)

```bash
cd frontend
npm install
```

### 데이터·벡터DB

평가·검색 경로는 Chroma 벡터 DB가 필요합니다. [data/README.md](data/README.md) 를 참고해 다음 순서로 준비하세요.

```bash
python scripts/download_data.py             # Nemotron-Personas-Korea → target_personas_20_59.jsonl
python scripts/build_vectordb.py --device cuda   # persona_db/ 생성
```

## 코드 스타일

- Python: `ruff check nemotron_ab backend scripts tests` / `black nemotron_ab backend scripts tests`
- TypeScript: `cd frontend && npm run lint`
- 줄 길이 110. import 정렬은 `ruff --select I` 기준.
- 주석은 의도·트레이드오프 설명에 사용하고, 코드가 이미 드러내는 사실을 중복 서술하지 않습니다.

## 커밋 규약

- [Conventional Commits](https://www.conventionalcommits.org/) 기반.
- 메시지 언어는 **한국어**.
- 예: `feat: 작업 큐 ETA 추정 로직 추가`, `fix: 벡터 검색 fanout 배수 누락 보정`.

## PR 절차

1. 새 브랜치 생성 (`feat/...`, `fix/...`, `chore/...`).
2. 로컬에서 다음을 통과시킨 뒤 푸시:
   - `ruff check nemotron_ab backend scripts`
   - `python -m nemotron_ab.worker_main --once` (임포트 무결성)
   - `cd frontend && npm run build`
3. `gh pr create` 또는 GitHub UI 로 PR 작성. 템플릿의 체크리스트를 채워주세요.
4. 머지 후에는 GitHub UI에서 브랜치를 삭제합니다.

## 보안·민감 정보

- 데이터셋·실행 로그는 가능하면 `data/`, `outputs/`, `persona_db/` 아래에 두세요(모두 git ignore 대상).
- 이미지 자산은 `outputs/jobs/job_<id>/assets/` 또는 `outputs/staging/` 에 저장됩니다.
- 비밀(API 키 등)은 환경 변수와 `.env` (gitignore) 로 관리합니다.

## 라이선스

- **소스 코드 기여**는 [Apache-2.0](LICENSE) 에 따라 배포됩니다. PR을내면 동일 조건으로 기여하는 것에 동의한 것으로 봅니다.
- **데이터·벡터DB**(`persona_db/`, HF 사전 빌드 DB 등)는 NVIDIA `Nemotron-Personas-Korea` 파생물로 **CC-BY-4.0** 입니다. 데이터 관련 PR·재배포 시 attribution 을 유지하세요.
- 서드파티 요약: [NOTICE](NOTICE)
