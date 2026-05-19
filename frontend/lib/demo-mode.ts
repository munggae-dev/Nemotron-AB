/** 백엔드·워커 없이 UI 데모용 목업 API (`npm run dev:demo`). */
export function isDemoMode(): boolean {
  return process.env.NEXT_PUBLIC_DEMO_MODE === "1" || process.env.NEXT_PUBLIC_DEMO_MODE === "true";
}

/** GitHub Pages 등 정적 호스팅용 — Route Handler 없이 브라우저·빌드 시 인라인 목업. */
export function isStaticDemo(): boolean {
  return process.env.NEXT_PUBLIC_DEMO_STATIC === "1" || process.env.NEXT_PUBLIC_DEMO_STATIC === "true";
}

/** 목업 핸들러를 HTTP 대신 직접 호출 (정적 데모 전용). */
export function isInlineMockApi(): boolean {
  return isDemoMode() && isStaticDemo();
}
