"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ConfirmDeleteJobDialog } from "@/components/ConfirmDeleteJobDialog";
import { apiDelete, apiGet, apiPost, type JobProgress, type JobRow } from "@/lib/api";
import { isJobDeletable } from "@/lib/job-display";
import { getApiBaseUrl } from "@/lib/api-base";

type ReportJson = Record<string, unknown>;

const BUCKET_LABEL: Record<string, string> = {
  "20s": "20대",
  "30s": "30대",
  "40s": "40대",
  "50s": "50대",
};

const BUCKET_ORDER = ["20s", "30s", "40s", "50s"] as const;

type OverallStats = {
  count: number;
  win_rate: { A: number; B: number };
  avg_score: { A: number; B: number };
  avg_confidence: number;
};

type BucketSummary = {
  count: number;
  win_rate: { A: number; B: number };
  avg_score: { A: number; B: number };
  avg_confidence: number;
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseOverall(report: Record<string, unknown>): OverallStats | null {
  const overall = report.overall;
  if (!isRecord(overall)) return null;
  const win = overall.win_rate;
  const avg = overall.avg_score;
  if (!isRecord(win) || !isRecord(avg)) return null;
  const count = Number(overall.count);
  const wa = Number(win.A);
  const wb = Number(win.B);
  const sa = Number(avg.A);
  const sb = Number(avg.B);
  const conf = Number(overall.avg_confidence);
  if (!Number.isFinite(count)) return null;
  return {
    count,
    win_rate: { A: wa, B: wb },
    avg_score: { A: sa, B: sb },
    avg_confidence: Number.isFinite(conf) ? conf : 0,
  };
}

function extractReportBlob(root: ReportJson | null): Record<string, unknown> | null {
  if (!root) return null;
  const r = root.report ?? root["report"];
  return isRecord(r) ? r : null;
}

function truncateCopy(s: string, n: number): string {
  const t = s.trim();
  if (t.length <= n) return t;
  return `${t.slice(0, n)}…`;
}

function parseJobPayload(raw: string | undefined): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    const o = JSON.parse(raw) as unknown;
    return typeof o === "object" && o !== null ? (o as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function payloadHasImage(payload: Record<string, unknown> | null, key: "image_a" | "image_b"): boolean {
  const ref = payload?.[key];
  if (!ref || typeof ref !== "object") return false;
  const v = (ref as Record<string, unknown>).value;
  return typeof v === "string" && v.trim().length > 0;
}

function formatPct(x: number, digits = 1): string {
  return `${(x * 100).toFixed(digits)}%`;
}

function formatDeltaPctPoints(a: number, b: number): string {
  const d = (b - a) * 100;
  const sign = d > 0 ? "+" : "";
  return `${sign}${d.toFixed(1)}%p`;
}

function scoreImprovement(a: number, b: number): string | null {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (Math.abs(a) < 1e-6) return null;
  const pct = ((b - a) / a) * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function formatDurationSec(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "—";
  if (sec < 60) return `${Math.round(sec)}초`;
  if (sec < 3600) return `약 ${Math.round(sec / 60)}분`;
  return `약 ${(sec / 3600).toFixed(1)}시간`;
}

function JobProgressPanel({ progress }: { progress: JobProgress }) {
  const indeterminate = progress.percent === null;
  const pct =
    progress.percent === null ? 0 : Math.min(100, Math.max(0, progress.percent));
  const etaLines: string[] = [];
  if (progress.eta_sec !== null && Number.isFinite(progress.eta_sec))
    etaLines.push(`남은 시간(추정) ${formatDurationSec(progress.eta_sec)}`);
  if (progress.eta_at)
    etaLines.push(
      `대략 이 시각 전후 완료: ${new Date(progress.eta_at).toLocaleString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        month: "short",
        day: "numeric",
      })}`,
    );
  if (progress.avg_sec_per_task !== null && Number.isFinite(progress.avg_sec_per_task))
    etaLines.push(`평균 처리 시간 약 ${formatDurationSec(progress.avg_sec_per_task)}/건`);

  const pctLabel =
    progress.percent !== null ? `${Number.isInteger(progress.percent) ? progress.percent : progress.percent.toFixed(1)}%` : null;

  return (
    <div className="job-progress-panel">
      <div className="job-progress-head">
        <span className="job-progress-phase">{progress.label}</span>
        <span className="muted" style={{ fontSize: 12 }}>
          {progress.detail}
        </span>
      </div>
      <div className={`job-progress-track${indeterminate ? " job-progress-track--indeterminate" : ""}`}>
        {!indeterminate ? <div className="job-progress-fill" style={{ width: `${pct}%` }} /> : null}
      </div>
      {pctLabel ? (
        <p className="job-progress-pct muted" style={{ margin: "8px 0 0", fontSize: 12 }}>
          진행도 {pctLabel}
        </p>
      ) : (
        <p className="muted" style={{ margin: "8px 0 0", fontSize: 12 }}>
          진행 중(세부 비율은 매칭이 끝나면 표시됩니다).
        </p>
      )}
      <ul className="job-progress-meta muted">
        {progress.elapsed_since_created_sec !== null &&
        progress.elapsed_since_created_sec !== undefined &&
        Number.isFinite(progress.elapsed_since_created_sec) &&
        progress.elapsed_since_created_sec >= 1 ? (
          <li>경과 (접수 후) {formatDurationSec(progress.elapsed_since_created_sec)}</li>
        ) : null}
        {progress.elapsed_sec !== null &&
        Number.isFinite(progress.elapsed_sec) &&
        progress.elapsed_sec >= 1 ? (
          <li>평가 구간 경과 (첫 호출 이후) {formatDurationSec(progress.elapsed_sec)}</li>
        ) : null}
        {etaLines.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
      {progress.note ? (
        <p className="job-progress-note muted" style={{ margin: "12px 0 0", fontSize: 12 }}>
          {progress.note}
        </p>
      ) : null}
      <p className="muted" style={{ margin: "10px 0 0", fontSize: 11 }}>
        진행 표시와 예상 시간은 약 3초 간격으로 갱신됩니다. 예상 시간은 현재 속도 기준이며 병렬·재시도에 따라 달라질 수 있습니다.
      </p>
    </div>
  );
}

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const idStr = typeof params?.id === "string" ? params.id : null;
  const [refreshKey, setRefreshKey] = useState(0);
  const [job, setJob] = useState<JobRow | null>(null);
  const [report, setReport] = useState<ReportJson | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reaggLoading, setReaggLoading] = useState(false);
  const [reaggErr, setReaggErr] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const reload = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  const jobRef = useRef<JobRow | null>(null);
  jobRef.current = job;

  const loadJob = useCallback(
    async (reset: boolean) => {
      if (!idStr) return;
      if (reset) {
        setErr(null);
        setReport(null);
      }
      try {
        const j = await apiGet<JobRow>(`/jobs/${idStr}`);
        setJob(j);
        if (j.status === "completed") {
          try {
            const r = await apiGet<ReportJson>(`/jobs/${idStr}/report`);
            setReport(r);
          } catch {
            if (reset) setReport(null);
          }
        }
      } catch (e: unknown) {
        if (!reset) return;
        setErr(e instanceof Error ? e.message : String(e));
      }
    },
    [idStr],
  );

  useEffect(() => {
    if (!idStr) return undefined;
    void loadJob(true);
    return undefined;
  }, [idStr, refreshKey, loadJob]);

  useEffect(() => {
    if (!idStr) return undefined;
    const id = window.setInterval(() => {
      const j = jobRef.current;
      if (!j || !["preparing", "pending", "running"].includes(j.status)) return;
      void loadJob(false);
    }, 3500);
    return () => window.clearInterval(id);
  }, [idStr, loadJob]);

  async function onReaggregate() {
    if (!idStr) return;
    setReaggErr(null);
    setReaggLoading(true);
    try {
      await apiPost<unknown>(`/jobs/${idStr}/report/reaggregate`, {});
      reload();
    } catch (e: unknown) {
      setReaggErr(e instanceof Error ? e.message : String(e));
    } finally {
      setReaggLoading(false);
    }
  }

  async function onConfirmDelete() {
    if (!idStr || !job) return;
    setDeleteErr(null);
    setDeleteLoading(true);
    try {
      await apiDelete<{ status: string; id: number }>(`/jobs/${idStr}`);
      setDeleteOpen(false);
      router.push("/jobs");
    } catch (e: unknown) {
      setDeleteErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleteLoading(false);
    }
  }

  const reportSection = extractReportBlob(report);
  const overall = reportSection ? parseOverall(reportSection) : null;
  const finalWinner =
    reportSection && typeof reportSection.final_winner === "string" ? reportSection.final_winner : null;
  const keyReasons = Array.isArray(reportSection?.key_reasons)
    ? (reportSection.key_reasons as unknown[]).filter((x): x is string => typeof x === "string")
    : [];
  const conditional = Array.isArray(reportSection?.conditional_recommendation)
    ? (reportSection.conditional_recommendation as Record<string, unknown>[])
    : [];
  const funnel = isRecord(report?.funnel) ? (report.funnel as Record<string, unknown>) : null;
  const funnelFlow = funnel && isRecord(funnel.flow) ? (funnel.flow as Record<string, unknown>) : null;
  const funnelFilter = funnel && isRecord(funnel.persona_filter) ? (funnel.persona_filter as Record<string, unknown>) : null;
  const summaryByBucket = isRecord(reportSection?.summary_by_bucket)
    ? (reportSection.summary_by_bucket as Record<string, BucketSummary>)
    : {};
  const campaign = isRecord(report?.campaign) ? (report.campaign as Record<string, unknown>) : null;
  const copyA =
    typeof campaign?.text_a === "string"
      ? (campaign.text_a as string)
      : typeof campaign?.copy_a === "string"
        ? (campaign.copy_a as string)
        : "";
  const copyB =
    typeof campaign?.text_b === "string"
      ? (campaign.text_b as string)
      : typeof campaign?.copy_b === "string"
        ? (campaign.copy_b as string)
        : "";
  const payloadParsed = parseJobPayload(typeof job?.payload_json === "string" ? job.payload_json : undefined);
  const showImgA = payloadHasImage(payloadParsed, "image_a");
  const showImgB = payloadHasImage(payloadParsed, "image_b");
  const runtimeSec =
    isRecord(report?.runtime) && typeof report.runtime.elapsed_sec === "number"
      ? report.runtime.elapsed_sec
      : null;

  const winnerIsB = finalWinner === "B";
  const winnerIsA = finalWinner === "A";

  let scoreBarA = 45;
  let scoreBarB = 55;
  if (overall) {
    const maxS = Math.max(overall.avg_score.A, overall.avg_score.B, 1e-6);
    scoreBarA = Math.round((overall.avg_score.A / maxS) * 100);
    scoreBarB = Math.round((overall.avg_score.B / maxS) * 100);
  }

  const improvement = overall ? scoreImprovement(overall.avg_score.A, overall.avg_score.B) : null;
  const confPct = overall ? Math.min(100, Math.max(0, overall.avg_confidence * 100)) : 0;

  return (
    <>
      {job?.status === "completed" && overall && report ? (
        <>
          <div className="report-page-head">
            <div>
              <nav className="report-breadcrumb" aria-label="breadcrumb">
                <Link href="/jobs">작업 큐</Link>
                <span className="material-symbols-outlined report-breadcrumb-sep" style={{ fontSize: 14 }}>
                  chevron_right
                </span>
                <span className="report-breadcrumb-current">{truncateCopy(job.title || `작업 #${idStr}`, 40)}</span>
              </nav>
              <h1>통계 리포트</h1>
            </div>
            <div className="report-actions">
              <button type="button" className="btn secondary" onClick={() => downloadJson(`job-${idStr}-report.json`, report)}>
                <span className="material-symbols-outlined" style={{ fontSize: 18, verticalAlign: "middle", marginRight: 6 }}>
                  download
                </span>
                JSON 내보내기
              </button>
              <button type="button" className="btn secondary" disabled={reaggLoading} onClick={() => void onReaggregate()}>
                <span className="material-symbols-outlined" style={{ fontSize: 18, verticalAlign: "middle", marginRight: 6 }}>
                  calculate
                </span>
                리포트 재집계
              </button>
              <button type="button" className="btn" onClick={() => reload()} disabled={reaggLoading}>
                <span className="material-symbols-outlined" style={{ fontSize: 18, verticalAlign: "middle", marginRight: 6 }}>
                  refresh
                </span>
                다시 불러오기
              </button>
              <button
                type="button"
                className="btn btn--danger"
                disabled={reaggLoading || deleteLoading}
                onClick={() => {
                  setDeleteErr(null);
                  setDeleteOpen(true);
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 18, verticalAlign: "middle", marginRight: 6 }}>
                  delete
                </span>
                삭제
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="page-header">
          <div>
            <p style={{ margin: "0 0 8px" }}>
              <Link href="/jobs">← 작업 큐</Link>
            </p>
            <h1 className="h1">작업 #{idStr ?? "…"}</h1>
          </div>
          {idStr ? (
            <div className="page-header-actions">
              <button type="button" className="btn secondary" onClick={() => reload()}>
                새로고침
              </button>
              {job && isJobDeletable(job.status) ? (
                <button
                  type="button"
                  className="btn btn--danger"
                  onClick={() => {
                    setDeleteErr(null);
                    setDeleteOpen(true);
                  }}
                >
                  삭제
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      {err && <div className="msg err">{err}</div>}
      {reaggErr && <div className="msg err">{reaggErr}</div>}

      {job?.status === "completed" && report && !overall && (
        <>
          <div className="msg err">리포트는 받았지만 요약 필드를 해석하지 못했습니다. 원본 JSON을 확인하세요.</div>
          <details className="raw-json-details">
            <summary>원본 JSON 보기</summary>
            <pre tabIndex={0}>{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}

      {job && !(job.status === "completed" && overall && report) && (
        <div className="card">
          <p style={{ marginTop: 0 }}>
            <strong>{job.title}</strong>
          </p>
          <p>
            상태:{" "}
            <span className="badge">
              {job.status === "preparing"
                ? "매칭 중"
                : job.status === "pending"
                  ? "대기"
                  : job.status === "running"
                    ? "실행 중"
                    : job.status === "completed"
                      ? "완료"
                      : job.status === "failed"
                        ? "실패"
                        : job.status}
            </span>
          </p>
          {job.error_message && <p style={{ color: "var(--error)" }}>{job.error_message}</p>}
          <p style={{ color: "var(--on-surface-variant)", fontSize: 14 }}>
            생성: {job.created_at}
            {job.finished_at && ` · 완료: ${job.finished_at}`}
          </p>
          {job.progress && ["preparing", "pending", "running"].includes(job.status) ? (
            <JobProgressPanel progress={job.progress} />
          ) : null}
          {job.status === "preparing" && (
            <p style={{ color: "var(--on-surface-variant)", marginBottom: 0 }}>
              API가 페르소나를 벡터DB에서 찾아 태스크를 붙이는 중입니다. 완료되면 대기 상태로 바뀌며, 이 페이지를 새로고침해 확인할 수 있습니다.
            </p>
          )}
          {(job.status === "pending" || job.status === "running") && (
            <p style={{ color: "var(--on-surface-variant)", marginBottom: 0 }}>
              워커가 처리 중이면 완료 후 이 페이지를 새로고침하거나 위의 다시 불러오기를 사용하세요.
            </p>
          )}
          {job.status === "completed" && !report && !err && (
            <p style={{ color: "var(--on-surface-variant)", marginBottom: 0 }}>보고서 파일을 불러올 수 없습니다.</p>
          )}
          {job.status === "completed" && report && !overall && !err && (
            <p style={{ color: "var(--on-surface-variant)", marginBottom: 0 }}>
              보고서 본문은 내려받았지만 필수 필드를 읽지 못했습니다. 아래 안내를 참고하세요.
            </p>
          )}
        </div>
      )}

      {job?.status === "completed" && overall && report && (
        <>
          <div className="report-metrics-row">
            <div className={`report-metric-card${winnerIsA ? " report-metric-card--winner" : ""}`}>
              {winnerIsA && <div className="report-winner-ribbon">WINNER</div>}
              <div className="report-metric-card-head">
                <div>
                  <span className="report-variant-eyebrow">VARIANT A</span>
                  <h3>안 A (기준)</h3>
                </div>
                <span className="material-symbols-outlined" style={{ color: "var(--outline)" }}>
                  info
                </span>
              </div>
              <div>
                <p className="report-metric-stat-label">평균 가중 점수</p>
                <div className="report-metric-big">
                  <span className="report-metric-big-num">{overall.avg_score.A.toFixed(2)}</span>
                  <span className="report-metric-sub">승률 {formatPct(overall.win_rate.A, 1)}</span>
                </div>
              </div>
              <div className="report-score-bar">
                <div
                  className="report-score-bar-fill report-score-bar-fill--muted"
                  style={{ width: `${scoreBarA}%` }}
                />
              </div>
            </div>

            <div className={`report-metric-card${winnerIsB ? " report-metric-card--winner" : ""}`}>
              {winnerIsB && <div className="report-winner-ribbon">WINNER</div>}
              <div className="report-metric-card-head">
                <div>
                  <span className="report-variant-eyebrow report-variant-eyebrow--primary">VARIANT B</span>
                  <h3>안 B (비교)</h3>
                </div>
                <span className="material-symbols-outlined" style={{ color: "var(--primary)", fontVariationSettings: '"FILL" 1' }}>
                  stars
                </span>
              </div>
              <div>
                <p className="report-metric-stat-label">평균 가중 점수</p>
                <div className="report-metric-big">
                  <span className={`report-metric-big-num${winnerIsB ? " report-metric-big-num--winner" : ""}`}>
                    {overall.avg_score.B.toFixed(2)}
                  </span>
                  <span className="report-metric-sub">승률 {formatPct(overall.win_rate.B, 1)}</span>
                </div>
                {improvement && (
                  <p className="report-improve-row">
                    <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                      trending_up
                    </span>
                    기준 대비 점수 {improvement}
                  </p>
                )}
              </div>
              <div className="report-score-bar">
                <div className="report-score-bar-fill report-score-bar-fill--primary" style={{ width: `${scoreBarB}%` }} />
              </div>
            </div>

            <div className="report-confidence-card">
              <div className="report-confidence-ring">
                <span>{confPct.toFixed(0)}%</span>
              </div>
              <div className="report-confidence-heading">
                <h4>평균 신뢰도</h4>
                <span className="field-help-wrap">
                  <button
                    type="button"
                    className="field-help-btn"
                    aria-label="평균 신뢰도 설명 보기"
                  >
                    <span className="material-symbols-outlined" aria-hidden>
                      help
                    </span>
                  </button>
                  <div className="field-help-tooltip field-help-tooltip--report" role="tooltip">
                    <p>
                      <strong>계산:</strong> 페르소나마다 A/B{" "}
                      <strong>가중 점수 차이</strong>(절댓값)를 0~100 점 스케일에서 최대 100으로 나눠 0~1로 둔 값을
                      개별 신뢰도로 쓰고, 표본 전체에서 그 <strong>산술평균</strong>을 구한 뒤 여기서는 %로
                      표시합니다.
                    </p>
                    <p>
                      <strong>해석:</strong> 숫자가 클수록 많은 페르소나에서 두 안의 점수가 서로{" "}
                      <strong>덜 비슷하게</strong> 갈렸다는 뜻입니다. 최종 추천 Variant와 별개의 보조 참고치입니다.
                    </p>
                    <p className="field-help-tooltip-note">
                      통계적 유의성(p값)·모형 불확실성을 의미하지 않습니다. 승률·평균 가중 점수·근거 문장과 함께
                      보시면 됩니다.
                    </p>
                  </div>
                </span>
              </div>
            </div>
          </div>

          <div className="report-section-card">
            <h3>연령 버킷별 요약</h3>
            <p className="section-sub">
              각 버킷에서 <strong>우세 판정(승률)</strong> 비율을 100% 스택 막대로 표시했습니다. 표의 승률·최종 추천과 같은
              기준입니다.
            </p>
            <div className="report-legend">
              <div className="report-legend-item">
                <span className="report-legend-dot report-legend-dot--a" />
                Variant A
              </div>
              <div className="report-legend-item">
                <span className="report-legend-dot report-legend-dot--b" />
                Variant B
              </div>
            </div>
            <div className="bucket-bars">
              {BUCKET_ORDER.map((bucket) => {
                const s = summaryByBucket[bucket];
                if (!s || typeof s.count !== "number" || s.count <= 0) return null;
                let wrA = Number(s.win_rate?.A);
                let wrB = Number(s.win_rate?.B);
                if (Number.isFinite(wrA) && Number.isFinite(wrB) && (wrA > 1 || wrB > 1)) {
                  wrA /= 100;
                  wrB /= 100;
                }
                const winOk =
                  Number.isFinite(wrA) &&
                  Number.isFinite(wrB) &&
                  wrA >= 0 &&
                  wrB >= 0 &&
                  wrA <= 1 &&
                  wrB <= 1 &&
                  Math.abs(wrA + wrB - 1) < 0.02;
                let normA: number;
                let normB: number;
                let barMode: "win" | "score_share" = "win";
                if (winOk) {
                  const sumW = wrA + wrB;
                  normA = sumW > 0 ? (wrA / sumW) * 100 : 50;
                  normB = sumW > 0 ? (wrB / sumW) * 100 : 50;
                } else {
                  barMode = "score_share";
                  const a = Number(s.avg_score?.A);
                  const b = Number(s.avg_score?.B);
                  const t = Number.isFinite(a) && Number.isFinite(b) && a >= 0 && b >= 0 ? a + b : 0;
                  normA = t > 0 ? (a / t) * 100 : 50;
                  normB = t > 0 ? (b / t) * 100 : 50;
                }
                const label = BUCKET_LABEL[bucket] ?? bucket;
                const avgA = s.avg_score?.A;
                const avgB = s.avg_score?.B;
                const scoreHint =
                  typeof avgA === "number" &&
                  typeof avgB === "number" &&
                  Number.isFinite(avgA) &&
                  Number.isFinite(avgB)
                    ? ` · 평균 가중 점수 A ${avgA.toFixed(1)} / B ${avgB.toFixed(1)}`
                    : "";
                const tipA =
                  barMode === "win"
                    ? `승률 A ${formatPct(wrA, 1)}${scoreHint}`
                    : `평균 가중 점수 비중 ~${normA.toFixed(0)}%(구버전 리포트 등 승률 없음)${scoreHint}`;
                const tipB =
                  barMode === "win"
                    ? `승률 B ${formatPct(wrB, 1)}${scoreHint}`
                    : `평균 가중 점수 비중 ~${normB.toFixed(0)}%(구버전 리포트 등 승률 없음)${scoreHint}`;
                return (
                  <div key={bucket} className="bucket-bar-row">
                    <strong>{label}</strong>
                    <div
                      className="bucket-bar-track"
                      style={{ gridTemplateColumns: `${normA}fr ${normB}fr` }}
                    >
                      <div className="bucket-bar-seg bucket-bar-seg--a" title={tipA}>
                        {normA >= 12 ? "A" : null}
                      </div>
                      <div className="bucket-bar-seg bucket-bar-seg--b" title={tipB}>
                        {normB >= 12 ? "B" : null}
                      </div>
                    </div>
                    <span className="bucket-bar-meta">n={s.count}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="report-detail-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>지표</th>
                  <th>Variant A</th>
                  <th>Variant B</th>
                  <th>델타</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>표본 수 (페르소나)</td>
                  <td className="mono-cell">{overall.count}</td>
                  <td className="mono-cell">{overall.count}</td>
                  <td className="mono-cell">—</td>
                </tr>
                <tr>
                  <td>평균 가중 점수</td>
                  <td className="mono-cell">{overall.avg_score.A.toFixed(3)}</td>
                  <td className="mono-cell">{overall.avg_score.B.toFixed(3)}</td>
                  <td className="mono-cell" style={{ fontWeight: 700, color: "var(--primary)" }}>
                    {(overall.avg_score.B - overall.avg_score.A).toFixed(3)}
                  </td>
                </tr>
                <tr>
                  <td>승률 (우세 비율)</td>
                  <td className="mono-cell">{formatPct(overall.win_rate.A)}</td>
                  <td className="mono-cell">{formatPct(overall.win_rate.B)}</td>
                  <td className="mono-cell" style={{ fontWeight: 700, color: "var(--primary)" }}>
                    {formatDeltaPctPoints(overall.win_rate.A, overall.win_rate.B)}
                  </td>
                </tr>
                <tr>
                  <td>최종 추천</td>
                  <td colSpan={3} style={{ fontWeight: 700 }}>
                    Variant {finalWinner ?? "—"} 선호
                  </td>
                </tr>
              </tbody>
            </table>
            <div className="report-detail-foot">
              집계 결과입니다. 실제 전환율이 아니라 페르소나 시뮬레이션 점수입니다.
              {runtimeSec !== null && ` 집계 소요: ${runtimeSec.toFixed(3)}s`}
            </div>
            {job?.tokens && Number(job.tokens.total_tokens) > 0 ? (
              <div className="report-detail-foot">
                토큰 사용량: prompt {Number(job.tokens.prompt_tokens).toLocaleString()} ·
                completion {Number(job.tokens.completion_tokens).toLocaleString()} ·
                total <strong>{Number(job.tokens.total_tokens).toLocaleString()}</strong>
                {job.tokens.task_count ? ` (${job.tokens.task_count}건 평가)` : ""}
              </div>
            ) : null}
          </div>

          {funnel && (
            <div className="report-section-card">
              <h3>퍼널 정보</h3>
              <p className="section-sub">이번 리포트 집계에 사용된 필터와 표본 흐름입니다.</p>
              <div className="report-detail-table-wrap" style={{ marginTop: 8 }}>
                <table>
                  <tbody>
                    <tr>
                      <td>선정 표본</td>
                      <td className="mono-cell">{Number(funnelFlow?.selected_personas ?? 0)}</td>
                    </tr>
                    <tr>
                      <td>평가 완료</td>
                      <td className="mono-cell">{Number(funnelFlow?.scored_personas ?? 0)}</td>
                    </tr>
                    <tr>
                      <td>실패/제외</td>
                      <td className="mono-cell">{Number(funnelFlow?.failed_personas ?? 0)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {funnelFilter ? (
                <details className="raw-json-details" style={{ marginTop: 10 }}>
                  <summary>적용 필터(JSON)</summary>
                  <pre tabIndex={0}>{JSON.stringify(funnelFilter, null, 2)}</pre>
                </details>
              ) : null}
            </div>
          )}

          <div className="copy-compare-grid">
            <div>
              <h3 className="section-title" style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 8 }}>
                <span className="material-symbols-outlined">visibility</span>
                텍스트 · 이미지 비교
              </h3>
              <div className="copy-compare-preview">
                <div>
                  <div className="copy-preview-label">Control (A)</div>
                  {showImgA && idStr ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      className="job-variant-thumb"
                      src={`${getApiBaseUrl()}/jobs/${idStr}/images/a`}
                      alt=""
                    />
                  ) : null}
                  <div className="copy-preview-box">{truncateCopy(copyA, 1200) || "—"}</div>
                </div>
                <div>
                  <div className="copy-preview-label copy-preview-label--b">Variant (B)</div>
                  {showImgB && idStr ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      className="job-variant-thumb"
                      src={`${getApiBaseUrl()}/jobs/${idStr}/images/b`}
                      alt=""
                    />
                  ) : null}
                  <div className="copy-preview-box copy-preview-box--b">{truncateCopy(copyB, 1200) || "—"}</div>
                </div>
              </div>
            </div>
            <div className="report-insight-card">
              <h3>핵심 인사이트</h3>
              <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>
                앞 줄은 표본 전체 집계 수치, 이어서 연령대별 요약, 마지막은{" "}
                <strong>최종 추천 Variant와 동일하게 우세로 판정된 표본</strong>에서 뽑은 LLM 근거입니다(
                「소수 의견」은 반대쪽 우세 표본 비율이 낮아도 존재할 수 있음).
              </p>
              <div className="report-insight-body">
                <div className="report-insight-icon">
                  <span className="material-symbols-outlined">lightbulb</span>
                </div>
                <div>
                  {keyReasons.length > 0 ? (
                    <>
                      <p>{keyReasons[0]}</p>
                      <ul className="muted" style={{ margin: "8px 0 0", paddingLeft: "1.1rem" }}>
                        {keyReasons.slice(1).map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p>추출된 요약 근거 문장이 없습니다. 원본 JSON에서 세부 페르소나 결과를 확인하세요.</p>
                  )}
                  {conditional.length > 0 && (
                    <p className="muted" style={{ marginTop: 12 }}>
                      <strong>조건부 추천:</strong>{" "}
                      {conditional
                        .map((c) => `${BUCKET_LABEL[String(c.bucket)] ?? c.bucket} → Variant ${c.winner}`)
                        .join(" · ")}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>

          <details className="raw-json-details">
            <summary>원본 JSON 보기</summary>
            <pre tabIndex={0}>{JSON.stringify(report, null, 2)}</pre>
          </details>
        </>
      )}
      <ConfirmDeleteJobDialog
        job={deleteOpen && job ? { id: job.id, title: job.title } : null}
        loading={deleteLoading}
        error={deleteErr}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => void onConfirmDelete()}
      />
    </>
  );
}
