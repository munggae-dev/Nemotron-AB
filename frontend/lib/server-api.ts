import "server-only";

import { getApiBaseUrl } from "./api-base";

/** 서버 컴포넌트 전용 fetch — 클라이언트 번들과 공유하지 않아 RSC 청크 충돌을 줄입니다. */
export async function serverApiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}
