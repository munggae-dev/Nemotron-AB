import Link from "next/link";
import { JobsListPanel } from "@/components/JobsListPanel";
import type { JobRow, QueueStats } from "@/lib/api";
import { serverApiGet } from "@/lib/server-api";

export default async function HomePage() {
  let jobs: JobRow[] = [];
  let stats: QueueStats | null = null;
  let unread = 0;
  let err: string | null = null;

  try {
    const [jobList, queueStats, unreadRes] = await Promise.all([
      serverApiGet<JobRow[]>("/jobs?omit_payload=true&limit=1"),
      serverApiGet<QueueStats>("/meta/queue-stats"),
      serverApiGet<{ count: number }>("/notifications/unread-count"),
    ]);
    jobs = jobList;
    stats = queueStats;
    unread = unreadRes.count;
  } catch (e: unknown) {
    err = e instanceof Error ? e.message : String(e);
  }

  const by = stats?.by_status ?? {};
  const countStatus = (s: string) => Number(by[s] ?? 0);
  const pending = stats ? countStatus("pending") : jobs.filter((j) => j.status === "pending").length;
  const running = stats ? countStatus("running") : jobs.filter((j) => j.status === "running").length;
  const completed = stats ? countStatus("completed") : jobs.filter((j) => j.status === "completed").length;
  const failed = stats ? countStatus("failed") : jobs.filter((j) => j.status === "failed").length;

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="h1">대시보드</h1>
          <p className="lede">
            페르소나 기반 A/B 검증 현황입니다. 작업 등록 후 워커를 실행하면 큐가 처리됩니다. 로컬에서는{" "}
            <code className="mono">python -m nemotron_ab.worker_main</code>, Docker Compose에서는{" "}
            <code className="mono">worker</code> 서비스를 사용하세요.
          </p>
        </div>
        <Link href="/jobs/new" className="btn" style={{ textAlign: "center" }}>
          새 검증 만들기
        </Link>
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
              <p className="kpi-card-foot">워커가 처리 중</p>
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
              <p className="kpi-card-foot">큐 순번 대기</p>
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
              <p className="kpi-card-foot">리포트 조회 가능</p>
            </div>
            <div className="kpi-card">
              <div>
                <div className="kpi-card-head">
                  <p className="kpi-card-label">실패</p>
                  <span className="material-symbols-outlined" style={{ fontSize: 22, color: "var(--error)" }}>
                    error
                  </span>
                </div>
                <p className="kpi-card-value">{failed}</p>
              </div>
              <p className="kpi-card-foot">
                <Link href="/jobs">작업 큐에서 확인 →</Link>
              </p>
            </div>
          </div>

          <div className="home-nav-grid" aria-label="주요 메뉴">
            <Link href="/jobs" className="home-nav-card">
              <span className="material-symbols-outlined home-nav-card-icon" aria-hidden>
                dashboard
              </span>
              <span className="home-nav-card-title">작업 큐</span>
              <span className="home-nav-card-desc">
                전체 {stats?.total ?? "—"}건 · 대기 {pending} · 실행 {running}
              </span>
            </Link>
            <Link href="/notifications" className="home-nav-card">
              <span className="material-symbols-outlined home-nav-card-icon" aria-hidden>
                notifications
              </span>
              <span className="home-nav-card-title">알림</span>
              <span className="home-nav-card-desc">
                {unread > 0 ? `읽지 않음 ${unread}건` : "새 알림 없음"}
              </span>
            </Link>
            <Link href="/reports" className="home-nav-card">
              <span className="material-symbols-outlined home-nav-card-icon" aria-hidden>
                analytics
              </span>
              <span className="home-nav-card-title">분석·보고서</span>
              <span className="home-nav-card-desc">완료 {completed}건 리포트</span>
            </Link>
          </div>

          <JobsListPanel
            className="jobs-list-panel--home"
            pageSize={10}
            headerLink={{ href: "/jobs", label: "전체 보기" }}
            emptyHint={
              <>
                등록된 작업이 없습니다. 상단 <strong>새 검증 만들기</strong>로 첫 작업을 등록하세요.
              </>
            }
          />
        </>
      )}

      <div className="card">
        <h2 className="section-title" style={{ marginTop: 0 }}>
          로컬 실행 체크리스트
        </h2>
        <ol style={{ margin: 0, paddingLeft: "1.25rem", color: "var(--on-surface-variant)", lineHeight: 1.7 }}>
          <li>
            API: <code className="mono">uvicorn backend.main:app --reload --port 8010</code> 또는{" "}
            <code className="mono">docker compose up</code>
          </li>
          <li>
            워커: <code className="mono">python -m nemotron_ab.worker_main</code> (Compose의 worker 서비스와 동일)
          </li>
          <li>이 UI에서 작업 등록 → 큐·알림·보고서 확인 (API는 기본 <code className="mono">/_nemotron_api</code> 프록시)</li>
        </ol>
      </div>
    </>
  );
}
