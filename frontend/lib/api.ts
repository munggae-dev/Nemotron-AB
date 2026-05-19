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

/** 완료 작업 등에 저장된 이미지를 받아 새 스테이징 asset_ref 로 올립니다(복제·수정용). */
export async function apiImportJobAssetFromJob(
  jobId: number,
  variant: "a" | "b",
): Promise<{ asset_ref: string }> {
  const r = await fetch(`${getApiBaseUrl()}/jobs/${jobId}/images/${variant}`, { cache: "no-store" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `이미지 불러오기 실패 (${variant})`);
  }
  const blob = await r.blob();
  const mime = blob.type || "image/jpeg";
  const ext = mime.includes("png") ? "png" : mime.includes("webp") ? "webp" : mime.includes("gif") ? "gif" : "jpg";
  const file = new File([blob], `job-${jobId}-variant-${variant}.${ext}`, { type: mime });
  return apiUploadJobAsset(file);
}

export async function apiPatch<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBaseUrl()}${path}`, { method: "PATCH" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBaseUrl()}${path}`, { method: "DELETE" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

/** 원본 payload 그대로 새 job으로 복제 등록. title만 옵션으로 덮어쓸 수 있음. */
export async function cloneJob(
  jobId: number,
  opts?: { title?: string },
): Promise<{ id: number }> {
  return apiPost<{ id: number }>(`/jobs/${jobId}/clone`, opts ?? {});
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

export type PersonaPopulationEstimate = {
  count: number;
  note?: string;
  capped?: boolean;
  scanned?: number;
};

export type TokenUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  task_count?: number;
  llm_call_count?: number;
  eval_call_count?: number;
  synthesis_call_count?: number;
  eval_total_tokens?: number;
  synthesis_total_tokens?: number;
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
  tokens?: TokenUsage;
  funnel?: {
    persona_filter?: Record<string, unknown>;
    flow?: {
      selected_personas?: number;
      scored_personas?: number;
      failed_personas?: number;
    };
  };
  synthesis_headline?: string;
  synthesis_generated_at?: string;
  synthesis_model?: string;
};

export type SynthesisContent = {
  headline?: string;
  executive_summary?: string;
  segment_notes?: string;
  action_items?: string[];
  limitations?: string;
  full_markdown?: string;
};

export type PersonaEvalRow = {
  persona_id?: string;
  age?: number;
  bucket?: string;
  winner?: string;
  weighted_score?: { A?: number; B?: number };
  confidence?: number;
  reason?: string;
};

export type SynthesisInputsUsed = {
  context?: string;
  text_a?: string;
  text_b?: string;
  multimodal?: boolean;
  aggregation?: {
    final_winner?: string;
    overall?: { count?: number };
    key_reasons?: string[];
    summary_by_bucket?: Record<string, unknown>;
    conditional_recommendation?: unknown[];
  };
  persona_evaluations?: PersonaEvalRow[];
  persona_evaluations_meta?: {
    total_rows?: number;
    included_rows?: number;
    truncated?: boolean;
    partial_jsonl_path?: string;
  };
};

export type SynthesisBlock = {
  generated_at?: string;
  model?: string;
  base_url?: string;
  base_url_host?: string;
  multimodal?: boolean;
  tokens?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
  content?: SynthesisContent | null;
  error?: string | null;
  inputs_used?: SynthesisInputsUsed;
  persona_evaluations_meta?: SynthesisInputsUsed["persona_evaluations_meta"];
};

export type SynthesizeReportBody = {
  llm_base_url?: string;
  llm_model?: string;
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
  /** GET /jobs/{id} 단건: 실행 중에도 누적된 토큰 사용량을 노출 */
  tokens?: TokenUsage | null;
};

export type QueueStats = {
  total: number;
  by_status: Record<string, number>;
};

export type JobsListPage = {
  items: JobRow[];
  total: number;
  limit: number;
  offset: number;
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
