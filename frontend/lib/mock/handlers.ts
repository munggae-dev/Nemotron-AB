import type { JobRow, JobsListPage, NotificationRow, ReportSummary } from "@/lib/api";
import {
  DEMO_IMAGE_A,
  DEMO_IMAGE_B,
  DEMO_PERSONA_FILTERS,
  DEMO_PERSONA_ROWS,
  DEMO_REGIONS,
  buildDemoReport,
} from "@/lib/mock/fixtures";
import { getDemoStore, queueStatsFromJobs, tickRunningJobs } from "@/lib/mock/store";

export type MockRequestInit = {
  method: string;
  path: string;
  searchParams: URLSearchParams;
  body?: unknown;
  formData?: FormData;
};

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function errResponse(message: string, status: number): Response {
  return jsonResponse({ detail: message }, status);
}

function parsePath(path: string): { pathname: string; searchParams: URLSearchParams } {
  const q = path.indexOf("?");
  if (q === -1) return { pathname: path, searchParams: new URLSearchParams() };
  return {
    pathname: path.slice(0, q),
    searchParams: new URLSearchParams(path.slice(q + 1)),
  };
}

function stripApiPrefix(path: string): string {
  let p = path.replace(/^\/+/, "");
  if (p.startsWith("_nemotron_api/")) p = p.slice("_nemotron_api/".length);
  if (p.startsWith("nemotron-mock-api/")) p = p.slice("nemotron-mock-api/".length);
  return `/${p}`;
}

function findJob(store: ReturnType<typeof getDemoStore>, id: number): JobRow | undefined {
  return store.jobs.find((j) => j.id === id);
}

function filterJobs(
  jobs: JobRow[],
  opts: { status?: string | null; q?: string | null; limit: number; offset: number; omitPayload: boolean },
): JobRow[] {
  let list = [...jobs].sort((a, b) => b.id - a.id);
  if (opts.status) list = list.filter((j) => j.status === opts.status);
  if (opts.q) {
    const qq = opts.q.toLowerCase();
    list = list.filter((j) => j.title.toLowerCase().includes(qq));
  }
  const slice = list.slice(opts.offset, opts.offset + opts.limit);
  return slice.map((j) => {
    const row = { ...j };
    if (opts.omitPayload) delete row.payload_json;
    return row;
  });
}

function addNotification(
  store: ReturnType<typeof getDemoStore>,
  jobId: number | null,
  type: string,
  title: string,
  message: string,
) {
  const row: NotificationRow = {
    id: store.nextNotificationId++,
    job_id: jobId,
    type,
    title,
    message,
    is_read: 0,
    created_at: new Date().toISOString(),
  };
  store.notifications.unshift(row);
}

function scheduleAutoComplete(store: ReturnType<typeof getDemoStore>, jobId: number) {
  const delayMs = 4500;
  setTimeout(() => {
    const job = findJob(store, jobId);
    if (!job || job.status !== "pending") return;
    const now = new Date().toISOString();
    job.status = "running";
    job.started_at = now;
    job.progress = {
      phase: "evaluating",
      label: "페르소나 평가",
      detail: "데모 자동 실행",
      tasks: { total: 8, pending: 0, running: 1, completed: 7, failed: 0 },
      percent: 88,
      elapsed_sec: 4,
      avg_sec_per_task: 0.5,
      eta_sec: 1,
      eta_at: new Date(Date.now() + 1000).toISOString(),
      note: null,
    };
    setTimeout(() => {
      const j = findJob(store, jobId);
      if (!j) return;
      j.status = "completed";
      j.finished_at = new Date().toISOString();
      j.progress = null;
      const demoReport = buildDemoReport(jobId);
      const rep = demoReport.report as Record<string, unknown>;
      j.report_summary = {
        final_winner: String(rep.final_winner ?? "B"),
        overall: rep.overall as ReportSummary["overall"],
        key_reasons: rep.key_reasons as string[] | undefined,
        runtime: { elapsed_sec: 5 },
        tokens: demoReport.tokens as ReportSummary["tokens"],
      };
      store.reports.set(jobId, demoReport);
      addNotification(store, jobId, "success", `작업 #${jobId} 완료`, "데모: 자동 완료되었습니다.");
    }, 1200);
  }, delayMs);
}

export async function handleMockRequest(init: MockRequestInit): Promise<Response> {
  const store = getDemoStore();
  tickRunningJobs(store);

  const { pathname, searchParams } = parsePath(init.path);
  const method = init.method.toUpperCase();
  const path = stripApiPrefix(pathname);

  // --- meta ---
  if (method === "GET" && path === "/meta/regions") {
    return jsonResponse(DEMO_REGIONS);
  }
  if (method === "GET" && path === "/meta/persona-filters") {
    return jsonResponse(DEMO_PERSONA_FILTERS);
  }
  if (method === "POST" && path === "/meta/persona-population-estimate") {
    const body = (init.body ?? {}) as Record<string, unknown>;
    const ageMin = Number(body.age_min ?? 19);
    const ageMax = Number(body.age_max ?? 59);
    const span = Math.max(1, ageMax - ageMin + 1);
    const count = Math.min(4200, Math.round(180 * span + Math.random() * 200));
    return jsonResponse({
      count,
      note: "데모 모드 추정값 (실제 persona_db 미사용)",
      capped: false,
      scanned: 50000,
    });
  }
  if (method === "GET" && path === "/meta/queue-stats") {
    return jsonResponse(queueStatsFromJobs(store.jobs));
  }

  // --- notifications ---
  if (method === "GET" && path === "/notifications/unread-count") {
    const count = store.notifications.filter((n) => n.is_read === 0).length;
    return jsonResponse({ count });
  }
  if (method === "GET" && path === "/notifications") {
    const limit = Number(searchParams.get("limit") ?? 50);
    return jsonResponse(store.notifications.slice(0, limit));
  }
  if (method === "PATCH" && path.match(/^\/notifications\/read-all$/)) {
    for (const n of store.notifications) n.is_read = 1;
    return jsonResponse({ status: "ok", updated: store.notifications.length });
  }
  const notifRead = path.match(/^\/notifications\/(\d+)\/read$/);
  if (method === "PATCH" && notifRead) {
    const id = Number(notifRead[1]);
    const n = store.notifications.find((x) => x.id === id);
    if (!n) return errResponse("not found", 404);
    n.is_read = 1;
    return jsonResponse(n);
  }

  // --- jobs assets ---
  if (method === "POST" && path === "/jobs/assets") {
    const ref = `demo/staging/${Date.now().toString(36)}.jpg`;
    return jsonResponse({ asset_ref: ref }, 201);
  }

  // --- jobs list / create ---
  if (method === "GET" && path === "/jobs") {
    const limit = Number(searchParams.get("limit") ?? 200);
    const offset = Number(searchParams.get("offset") ?? 0);
    const status = searchParams.get("status");
    const q = searchParams.get("q");
    const omitPayload = searchParams.get("omit_payload") === "true";
    const includeTotal = searchParams.get("include_total") === "true";
    const items = filterJobs(store.jobs, { status, q, limit, offset, omitPayload });
    if (!includeTotal) return jsonResponse(items);
    let all = [...store.jobs];
    if (status) all = all.filter((j) => j.status === status);
    if (q) {
      const qq = q.toLowerCase();
      all = all.filter((j) => j.title.toLowerCase().includes(qq));
    }
    const page: JobsListPage = { items, total: all.length, limit, offset };
    return jsonResponse(page);
  }

  if (method === "POST" && path === "/jobs") {
    const body = (init.body ?? {}) as Record<string, unknown>;
    const id = store.nextJobId++;
    const title = String(body.title ?? `데모 작업 #${id}`);
    const payload = { ...body, evaluator: body.evaluator ?? "mock" };
    const row: JobRow = {
      id,
      title,
      status: "pending",
      created_at: new Date().toISOString(),
      payload_json: JSON.stringify(payload),
    };
    store.jobs.unshift(row);
    addNotification(store, id, "info", `작업 #${id} 등록`, "데모 큐에 추가되었습니다. 잠시 후 자동 완료됩니다.");
    scheduleAutoComplete(store, id);
    return jsonResponse({ id }, 201);
  }

  const jobImages = path.match(/^\/jobs\/(\d+)\/images\/(a|b)$/);
  if (method === "GET" && jobImages) {
    const variant = jobImages[2] as "a" | "b";
    const url = variant === "a" ? DEMO_IMAGE_A : DEMO_IMAGE_B;
    return Response.redirect(url, 302);
  }

  const jobClone = path.match(/^\/jobs\/(\d+)\/clone$/);
  if (method === "POST" && jobClone) {
    const srcId = Number(jobClone[1]);
    const src = findJob(store, srcId);
    if (!src) return errResponse("job not found", 404);
    const id = store.nextJobId++;
    const opts = (init.body ?? {}) as { title?: string };
    const row: JobRow = {
      ...src,
      id,
      title: opts.title?.trim() || `${src.title} (복제)`,
      status: "pending",
      created_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
      error_message: null,
      progress: null,
      report_summary: null,
    };
    store.jobs.unshift(row);
    scheduleAutoComplete(store, id);
    return jsonResponse({ id }, 201);
  }

  const jobSynth = path.match(/^\/jobs\/(\d+)\/report\/synthesize$/);
  if (method === "POST" && jobSynth) {
    const jobId = Number(jobSynth[1]);
    const job = findJob(store, jobId);
    if (!job || job.status !== "completed") return errResponse("completed job required", 400);
    const report = store.reports.get(jobId) ?? buildDemoReport(jobId);
    const body = (init.body ?? {}) as { llm_model?: string; llm_base_url?: string };
    const syn = {
      ...(report.synthesis as object),
      generated_at: new Date().toISOString(),
      model: body.llm_model ?? "demo-synthesis",
      base_url: body.llm_base_url ?? "http://localhost:11434/v1",
      content: {
        headline: "데모: 종합 분석을 다시 생성했습니다",
        executive_summary: "POST /report/synthesize 데모 응답입니다. 실제 LLM 호출은 없습니다.",
        action_items: ["데모 데이터로 UI 흐름만 확인하세요"],
        full_markdown: "## 데모 재생성\n\n실제 API 없이 UI만 갱신됩니다.",
      },
    };
    const next = { ...report, synthesis: syn };
    store.reports.set(jobId, next);
    return jsonResponse(next);
  }

  const jobPartial = path.match(/^\/jobs\/(\d+)\/partial-evaluations$/);
  if (method === "GET" && jobPartial) {
    return jsonResponse({
      rows: DEMO_PERSONA_ROWS,
      meta: { total_rows: 48, included_rows: DEMO_PERSONA_ROWS.length, truncated: true },
    });
  }

  const jobReport = path.match(/^\/jobs\/(\d+)\/report$/);
  if (method === "GET" && jobReport) {
    const jobId = Number(jobReport[1]);
    const job = findJob(store, jobId);
    if (!job || job.status !== "completed") return errResponse("report not ready", 404);
    const report = store.reports.get(jobId) ?? buildDemoReport(jobId);
    store.reports.set(jobId, report);
    return jsonResponse(report);
  }

  const jobOne = path.match(/^\/jobs\/(\d+)$/);
  if (jobOne && method === "GET") {
    const jobId = Number(jobOne[1]);
    const job = findJob(store, jobId);
    if (!job) return errResponse("job not found", 404);
    return jsonResponse({ ...job });
  }

  if (jobOne && method === "DELETE") {
    const jobId = Number(jobOne[1]);
    const idx = store.jobs.findIndex((j) => j.id === jobId);
    if (idx === -1) return errResponse("job not found", 404);
    store.jobs.splice(idx, 1);
    store.reports.delete(jobId);
    return jsonResponse({ status: "deleted", id: jobId });
  }

  if (method === "GET" && path === "/health") {
    return jsonResponse({ status: "ok", mode: "demo" });
  }

  return errResponse(`데모 API: ${method} ${path} 미구현`, 404);
}

/** fetch URL 또는 path 문자열을 받아 목업 응답을 반환합니다. */
export async function mockFetch(input: string, init?: RequestInit): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  let path = input;
  try {
    const u = new URL(input);
    path = u.pathname + u.search;
  } catch {
    /* relative path */
  }

  let body: unknown;
  if (init?.body && typeof init.body === "string") {
    try {
      body = JSON.parse(init.body);
    } catch {
      body = init.body;
    }
  }

  await new Promise((r) => setTimeout(r, 80 + Math.random() * 120));

  return handleMockRequest({
    method,
    path,
    searchParams: new URLSearchParams(),
    body,
  });
}
