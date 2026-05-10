import { getApiBaseUrl } from "./api-base";

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

/** 이미지 스테이징 업로드 → POST /jobs 에서 image_* 에 asset_ref 로 전달 */
export async function apiUploadJobAsset(file: File): Promise<{ asset_ref: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${getApiBaseUrl()}/jobs/assets`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<{ asset_ref: string }>;
}

export async function apiPatch<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBaseUrl()}${path}`, { method: "PATCH" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

export type KoreaRegions = Record<string, string[]>;

export type PersonaFilterEnumField = {
  key: string;
  label: string;
  options: { value: string; label: string }[];
};

export type MetaPersonaFilters = {
  dataset: string;
  age_range_note?: string;
  enum_fields: PersonaFilterEnumField[];
  occupation_contains: { max_chars: number };
  vectordb_hint?: string;
};

export type ReportSummary = {
  final_winner?: string;
  overall?: {
    count?: number;
    win_rate?: { A: number; B: number };
    avg_score?: { A: number; B: number };
    avg_confidence?: number;
  };
  key_reasons?: string[];
  runtime?: { elapsed_sec?: number };
};

export type JobProgress = {
  phase: string;
  label: string;
  detail: string;
  tasks: {
    total: number;
    pending: number;
    running: number;
    completed: number;
    failed: number;
  };
  /** 준비 중 등 구간에서는 null 일 수 있음 */
  percent: number | null;
  /** 첫 페르소나 평가 시작(jobs.started_at) 이후, ETA 산출에도 사용(서버 UTC 기준) */
  elapsed_sec: number | null;
  /** 작업 생성(접수) 시각 이후 전체 경과 */
  elapsed_since_created_sec?: number | null;
  avg_sec_per_task: number | null;
  eta_sec: number | null;
  eta_at: string | null;
  note: string | null;
};

export type JobRow = {
  id: number;
  title: string;
  status: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  /** GET /jobs/{id} 단건 등에서 포함될 수 있음 */
  payload_json?: string;
  /** 진행 중 작업 단건 조회 시 태스크 집계·ETA */
  progress?: JobProgress | null;
  /** GET /jobs 기본 응답: DB에 저장된 요약(완료 건만 채워짐) */
  report_summary?: ReportSummary | null;
};

export type QueueStats = {
  total: number;
  by_status: Record<string, number>;
};

export type NotificationRow = {
  id: number;
  job_id: number | null;
  type: string;
  title: string;
  message: string;
  is_read: number;
  created_at: string;
};
