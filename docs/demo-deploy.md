# UI 데모 배포

FastAPI·워커·Chroma·Ollama 없이 Nemotron-AB **UI만** 배포하는 방법입니다.

## 배포 방식 비교

| 방식 | 명령 | 호스팅 예시 | Node 서버 |
|------|------|-------------|-----------|
| **정적 (권장 시연)** | `npm run build:demo:static` | GitHub Pages, S3, Cloudflare Pages | 불필요 |
| Docker 데모 | `docker compose -f docker-compose.demo.yml up` | VM, Railway | 필요 |
| 로컬 개발 | `npm run dev:demo` | — | 필요 |

## 정적 호스팅 (GitHub Pages 등)

목업 API가 **브라우저 안에서** 동작합니다 (`NEXT_PUBLIC_DEMO_STATIC=1`). 빌드 결과는 `frontend/out/` HTML·JS·CSS 뿐입니다.

### 빌드

```bash
cd frontend
npm ci

# 사용자/조직 페이지 (username.github.io) — basePath 없음
npm run build:demo:static

# 프로젝트 페이지 (username.github.io/repo-name/) — basePath 필수
NEXT_PUBLIC_BASE_PATH=/nemotron-ab npm run build:demo:static
```

로컬 미리보기:

```bash
npx --yes serve out -l 3456
# → http://localhost:3456  (basePath 쓴 경우 경로 포함)
```

### GitHub Pages (Actions 예시)

`.github/workflows/demo-pages.yml` 을 저장소에 두거나, 수동으로 `out/` 을 `gh-pages` 브랜치에 푸시합니다.

핵심 단계:

1. `cd frontend && npm ci`
2. `NEXT_PUBLIC_BASE_PATH=/${{ github.event.repository.name }} npm run build:demo:static`
3. `actions/upload-pages-artifact` / `actions/deploy-pages` 로 `frontend/out` 배포

저장소 **Settings → Pages → Build: GitHub Actions** 를 선택합니다.

### 정적 데모 제한

- 작업·알림 데이터는 **탭을 닫으면 초기화**됩니다 (인메모리).
- 작업 상세 URL은 빌드 시 **#901–#920** 경로만 HTML로 생성됩니다. 그 밖의 ID는 클라이언트 이동으로만 열리며, **새로고침 시 404**가 날 수 있습니다.
- 샘플 완료 리포트: **작업 #901**

## Docker (Node 단일 컨테이너)

```bash
docker compose -f docker-compose.demo.yml up --build
```

`NEXT_PUBLIC_DEMO_STATIC` 없이 `/nemotron-mock-api` Route Handler를 사용합니다. 서버 하나에서 목업 상태가 유지됩니다.

## 로컬 개발

```bash
cd frontend
npm run dev:demo          # Node + Route Handler
npm run dev               # + NEXT_PUBLIC_DEMO_STATIC=1 in .env.local → 인라인 목업
```

## 환경 변수

| 변수 | 용도 |
|------|------|
| `NEXT_PUBLIC_DEMO_MODE=1` | 데모 UI·목업 API 활성화 |
| `NEXT_PUBLIC_DEMO_STATIC=1` | 정적 export + 인라인 목업 (`build:demo:static`에서 설정) |
| `NEXT_PUBLIC_BASE_PATH=/repo` | GitHub Pages 프로젝트 사이트 하위 경로 |

## 관련 파일

- `frontend/scripts/build-static-demo.mjs` — 정적 빌드 (Route Handler 임시 제거)
- `frontend/lib/mock/` — fixtures·store·handlers
- `frontend/app/jobs/[id]/layout.tsx` — 정적 export용 `generateStaticParams`
- `docker-compose.demo.yml` — Docker 데모
