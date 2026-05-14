import Link from "next/link";
import type { JobRow, QueueStats } from "@/lib/api";
import { serverApiGet } from "@/lib/server-api";

export const dynamic = "force-dynamic";

function statusPill(status: string): { cls: string; label: string } {
  if (status === "completed") return { cls: "status-pill status-pill--completed", label: "완료" };
  if (status === "failed") return { cls: "status-pill status-pill--failed", label: "실패" };
  if (status === "running") return { cls: "status-pill status-pill--running", label: "실행 중" };
  if (status === "preparing")
    return { cls: "status-pill status-pill--preparing", label: "매칭 중" };
  return { cls: "status-pill status-pill--pending", label: "대기" };
}

function formatWhen(iso: string): string {
  try {
    const d = new Date(iso.replace(" ", "T"));
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

export default async function JobsPage() {
  let jobs: JobRow[] = [];
  let stats: QueueStats | null = null;
  let err: string | null = null;
  let statsErr: string | null = null;
  try {
    jobs = await serverApiGet<JobRow[]>("/jobs?omit_payload=true");
  } catch (e: unknown) {
    err = e instanceof Error ? e.message : String(e);
  }
  try {
    stats = await serverApiGet<QueueStats>("/meta/queue-stats");
  } catch (e: unknown) {
    statsErr = e instanceof Error ? e.message : String(e);
  }

  const by = stats?.by_status ?? {};
  const countStatus = (s: string) => Number(by[s] ?? 0);

  const pending = stats ? countStatus("pending") : jobs.filter((j) => j.status === "pending").length;
  const running = stats ? countStatus("running") : jobs.filter((j) => j.status === "running").length;
  const completed = stats ? countStatus("completed") : jobs.filter((j) => j.status === "completed").length;
  const failed = stats ? countStatus("failed") : jobs.filter((j) => j.status === "failed").length;

  const totalListed = jobs.length;
  const totalAll = stats?.total ?? totalListed;
  const incomplete = pending + running + failed;
  const denom = Math.max(totalAll, 1);
  const completePct = Math.round((completed / denom) * 100);
  const incompletePct = Math.round((incomplete / denom) * 100);
  const barMax = Math.max(completed, incomplete, 1);
  const hComplete = Math.round((completed / barMax) * 100);
  const hIncomplete = Math.round((incomplete / barMax) * 100);

  const segPending = (pending / denom) * 100;
  const segRunning = (running / denom) * 100;
  const segCompleted = (completed / denom) * 100;
  const segFailed = (failed / denom) * 100;

  const sorted = [...jobs].sort((a, b) => b.id - a.id);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="h1">작업 큐</h1>
          <p className="lede">등록된 검증 작업 상태를 한눈에 보고 상세 분석으로 이동합니다.</p>
        </div>
        <Link href="/jobs/new" className="btn" style={{ textAlign: "center" }}>
          새 검증
        </Link>
      </div>

      <div className="dashboard-lede">
        <h2>큐 개요</h2>
        <p>워커가 실행 중이면 대기·실행 상태가 바뀌며, 완료 후 같은 행에서 분석 리포트를 열 수 있습니다.</p>
      </div>

      {err && <div className="msg err">{err}</div>}
      {statsErr && !err && (
        <div className="msg err" style={{ background: "var(--surface-container-high)", borderColor: "var(--outline-variant)", color: "var(--on-surface-variant)" }}>
          큐 통계 API를 불러오지 못했습니다({statsErr}). KPI는 현재 목록 기준으로 계산했습니다.
        </div>
      )}

      {!err && (
        <>
          <div className="kpi-grid">
            <div className="kpi-card">
              <div>
                <div className="kpi-card-head">
                  <p className="kpi-card-label">실행 중</p>
                  <span className="material-symbols-outlined kpi-card-value--primary" style={{ fontSize: 22 }}>
                    bolt
                  </span>
                </div>
                <p className="kpi-card-value kpi-card-value--primary">{running}</p>
              </div>
              <p className="kpi-card-foot">현재 워커가 처리 중인 작업</p>
            </div>
            <div className="kpi-card">
              <div>
                <div className="kpi-card-head">
                  <p className="kpi-card-label">대기</p>
                  <span className="material-symbols-outlined" style={{ fontSize: 22, color: "var(--outline)" }}>
                    schedule
                  </span>
                </div>
                <p className="kpi-card-value">{pending}</p>
              </div>
              <p className="kpi-card-foot">큐에서 순번 대기</p>
            </div>
            <div className="kpi-card">
              <div>
                <div className="kpi-card-head">
                  <p className="kpi-card-label">완료</p>
                  <span className="material-symbols-outlined" style={{ fontSize: 22, color: "var(--success)" }}>
                    check_circle
                  </span>
                </div>
                <p className="kpi-card-value">{completed}</p>
              </div>
              <p className="kpi-card-foot">
                리포트 조회 가능
                {stats && totalAll > totalListed ? ` · DB 전체 ${totalAll}건 중 목록 ${totalListed}건` : null}
              </p>
            </div>
            <div className="kpi-card kpi-card--cta">
              <div>
                <p className="kpi-card-label">다음 단계</p>
                <p className="kpi-card-value">A/B 검증</p>
                <p>텍스트·이미지 두 안을 넣고 페르소나 필터를 지정한 뒤 큐에 올려 보세요.</p>
              </div>
              <Link href="/jobs/new" className="btn-cta-inline">
                새 테스트 만들기
              </Link>
            </div>
          </div>

          <div className="queue-bento">
            <div className="panel-rounded">
              <div className="panel-rounded-head">
                <h3>최근 작업</h3>
                <Link href="/reports" className="topbar-icon-btn" style={{ fontSize: 12, fontWeight: 700, width: "auto", padding: "8px 12px", color: "var(--primary)" }}>
                  완료 분석 목록
                </Link>
              </div>
              {sorted.length === 0 ? (
                <div style={{ padding: 32, color: "var(--on-surface-variant)" }}>
                  등록된 작업이 없습니다. <Link href="/jobs/new">새 검증</Link>으로 시작하세요.
                </div>
              ) : (
                <div className="jobs-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>작업명</th>
                        <th>상태</th>
                        <th>추천</th>
                        <th className="text-right">생성</th>
                        <th className="text-right">분석</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.map((j) => {
                        const pill = statusPill(j.status);
                        return (
                          <tr key={j.id}>
                            <td>
                              <Link href={`/jobs/${j.id}`} className="job-title-link">
                                {j.title || `작업 #${j.id}`}
                              </Link>
                              <p className="job-sub">ID #{j.id}</p>
                            </td>
                            <td>
                              <span className={pill.cls}>
                                <span className="status-pill-dot" aria-hidden />
                                {pill.label}
                              </span>
                            </td>
                            <td className="mono-cell">
                              {j.status === "completed" && j.report_summary?.final_winner ? (
                                <span style={{ fontWeight: 700, color: "var(--primary)" }}>Variant {j.report_summary.final_winner}</span>
                              ) : (
                                <span style={{ color: "var(--outline)" }}>—</span>
                              )}
                            </td>
                            <td className="text-right mono-cell" style={{ whiteSpace: "nowrap", color: "var(--on-surface-variant)" }}>
                              {formatWhen(j.created_at)}
                            </td>
                            <td className="text-right">
                              <span style={{ display: "inline-flex", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
                                <Link href={`/jobs/${j.id}`}>{j.status === "completed" ? "리포트 열기" : "상세"}</Link>
                                <Link href={`/jobs/new?fromJob=${j.id}`} style={{ color: "var(--on-surface-variant)" }}>
                                  복제·수정
                                </Link>
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="queue-side-stack">
              <div className="panel-rounded" style={{ padding: 24 }}>
                <p className="queue-mini-head">큐 상태 비교</p>
                <div className="queue-stack-visual">
                  <div className="queue-stack-col">
                    <div className="queue-stack-col-label">미완료</div>
                    <div className="queue-stack-col-chart queue-stack-col-chart--a">
                      <div
                        className="queue-stack-bar-inner queue-stack-bar-inner--a"
                        style={{ height: `${Math.max(hIncomplete, 8)}%` }}
                        title={`대기+실행+실패: ${incomplete}`}
                      />
                    </div>
                    <p className="queue-stack-foot">{incompletePct}%</p>
                  </div>
                  <div className="queue-stack-col">
                    <div className="queue-stack-col-label">완료</div>
                    <div className="queue-stack-col-chart queue-stack-col-chart--b">
                      <div
                        className="queue-stack-bar-inner queue-stack-bar-inner--b"
                        style={{ height: `${Math.max(hComplete, 8)}%` }}
                        title={`완료: ${completed}`}
                      />
                    </div>
                    <p className="queue-stack-foot">{completePct}%</p>
                  </div>
                </div>
                <div className="queue-lift-row">
                  <span>전체 작업 수</span>
                  <span>{totalAll}</span>
                </div>
                <div className="queue-progress-bg">
                  <div className="queue-progress-fill" style={{ width: `${completePct}%` }} />
                </div>
                {totalAll > 0 && (
                  <div className="queue-segment-bar" aria-hidden title="상태 비율">
                    <span style={{ width: `${segPending}%`, background: "var(--surface-container-highest)" }} />
                    <span style={{ width: `${segRunning}%`, background: "var(--secondary-fixed)" }} />
                    <span style={{ width: `${segCompleted}%`, background: "var(--success)" }} />
                    <span style={{ width: `${segFailed}%`, background: "var(--error-container)" }} />
                  </div>
                )}
              </div>

              <div className="queue-tip-card">
                <div className="queue-tip-head">
                  <span className="material-symbols-outlined">tips_and_updates</span>
                  <strong>운영 팁</strong>
                </div>
                <p>
                  터미널에서 <code className="mono">python -m nemotron_ab.worker_main</code> 워커를 띄워 두면 대기 작업이 순차 처리되며,
                  완료 시 알림과 분석 리포트가 준비됩니다.
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
