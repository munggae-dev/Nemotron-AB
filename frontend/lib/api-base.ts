import { isDemoMode, isInlineMockApi } from "./demo-mode";

function demoApiOrigin(): string {
  if (typeof window !== "undefined") return window.location.origin;
  const port = process.env.PORT ?? "3000";
  const host = process.env.HOSTNAME ?? "127.0.0.1";
  return `http://${host}:${port}`;
}

/** 클라이언트·서버 공통: API 베이스 URL (환경 변수와 동일 규칙). */
export function getApiBaseUrl(): string {
  if (isInlineMockApi()) {
    return typeof window !== "undefined" ? window.location.origin : "";
  }
  if (isDemoMode()) {
    return `${demoApiOrigin()}/nemotron-mock-api`;
  }

  const explicit = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/$/, "");
  if (explicit) return explicit;

  const internal =
    process.env.API_INTERNAL_URL?.trim().replace(/\/$/, "") || "http://127.0.0.1:8010";

  if (typeof window === "undefined") {
    return internal;
  }
  return `${window.location.origin}/_nemotron_api`;
}
