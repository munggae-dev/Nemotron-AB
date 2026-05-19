import Link from "next/link";
import { JobsListPanel } from "@/components/JobsListPanel";
import type { QueueStats } from "@/lib/api";
import { serverApiGet } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  let stats: QueueStats | null = null;
  let err: string | null = null;

  try {
    stats = await serverApiGet<QueueStats>("/meta/queue-stats");
  } catch (e: unknown) {
    err = e instanceof Error ? e.message : String(e);
  }

  const by = stats?.by_status ?? {};
  const countStatus = (s: string) => Number(by[s] ?? 0);

  const pending = stats ? countStatus("pending") : 0;
  const running = stats ? countStatus("running") : 0;
  const completed = stats ? countStatus("completed") : 0;
  const failed = stats ? countStatus("failed") : 0;

  const totalAll = stats?.total ?? 0;
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
              <p className="kpi-card-foot">리포트 조회 가능 · DB 전체 {totalAll}건</p>
            </div>
          </div>

          <div className="queue-bento">
            <JobsListPanel
              pageSize={10}
              showCloneLink
              headerLink={{ href: "/reports", label: "완료 분석 목록" }}
            />

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
