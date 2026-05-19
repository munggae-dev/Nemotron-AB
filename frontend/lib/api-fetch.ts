import { getApiBaseUrl } from "./api-base";
import { isInlineMockApi } from "./demo-mode";
import { mockFetch } from "./mock/handlers";

/** 클라이언트·서버 공통 API fetch (정적 데모는 인라인 목업, Docker 데모는 /nemotron-mock-api). */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  if (isInlineMockApi()) {
    const mockPath = path.startsWith("http") ? new URL(path).pathname + new URL(path).search : path;
    return mockFetch(mockPath, init);
  }

  const url = path.startsWith("http") ? path : `${getApiBaseUrl()}${path}`;
  return fetch(url, { cache: "no-store", ...init });
}
