/** 클라이언트·서버 공통: API 베이스 URL (환경 변수와 동일 규칙). */
export function getApiBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://127.0.0.1:8010"
  );
}
