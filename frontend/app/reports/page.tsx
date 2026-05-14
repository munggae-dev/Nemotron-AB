import Link from "next/link";
import type { JobRow } from "@/lib/api";
import { serverApiGet } from "@/lib/server-api";

export const dynamic = "force-dynamic";

function formatDuration(sec?: number): string {
  if (typeof sec !== "number" || !Number.isFinite(sec) || sec < 0) return "—";
  if (sec < 60) return `${sec.toFixed(1)}초`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}분 ${s}초`;
}

export default async function ReportsIndexPage() {
  let jobs: JobRow[] = [];
  let err: string | null = null;
  try {
    jobs = await serverApiGet<JobRow[]>("/jobs?omit_payload=true&status=completed");
  } catch (e: unknown) {
    err = e instanceof Error ? e.message : String(e);
  }

  const completed = [...jobs].filter((j) => j.status === "completed").sort((a, b) => b.id - a.id);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="h1">분석·결과</h1>
          <p className="lede">완료된 검증 작업의 통계 리포트로 이동합니다. 진행 중인 작업은 작업 큐에서 상태를 확인하세요.</p>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link href="/jobs" className="btn secondary" style={{ textAlign: "center" }}>
            작업 큐
          </Link>
          <Link href="/jobs/new" className="btn" style={{ textAlign: "center" }}>
            새 검증
          </Link>
        </div>
      </div>

      {err && <div className="msg err">{err}</div>}

      {!err && completed.length === 0 && (
        <div className="panel-rounded" style={{ padding: 28 }}>
          <p style={{ margin: 0, color: "var(--on-surface-variant)", lineHeight: 1.6 }}>
            아직 완료된 작업이 없습니다. <Link href="/jobs/new">새 검증</Link>을 등록하고 워커를 실행하면 여기에 분석 링크가 쌓입니다.
          </p>
        </div>
      )}

      {!err && completed.length > 0 && (
        <div className="panel-rounded">
          <div className="panel-rounded-head">
            <h3>완료된 분석 리포트</h3>
            <span style={{ fontSize: 12, color: "var(--on-surface-variant)", fontWeight: 600 }}>{completed.length}건</span>
          </div>
          <div className="jobs-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>작업</th>
                  <th>추천</th>
                  <th>수행시간</th>
                  <th>완료 시각</th>
                  <th className="text-right">리포트</th>
                </tr>
              </thead>
              <tbody>
                {completed.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link href={`/jobs/${j.id}`} className="job-title-link">
                        {j.title || `작업 #${j.id}`}
                      </Link>
                      <p className="job-sub">ID #{j.id}</p>
                    </td>
                    <td className="mono-cell">
                      {j.report_summary?.final_winner ? (
                        <span style={{ fontWeight: 700, color: "var(--primary)" }}>Variant {j.report_summary.final_winner}</span>
                      ) : (
                        <span style={{ color: "var(--outline)" }}>—</span>
                      )}
                    </td>
                    <td className="mono-cell" style={{ whiteSpace: "nowrap" }}>
                      {formatDuration(j.report_summary?.runtime?.elapsed_sec)}
                    </td>
                    <td className="mono-cell" style={{ color: "var(--on-surface-variant)", whiteSpace: "nowrap" }}>
                      {j.finished_at ?? "—"}
                    </td>
                    <td className="text-right">
                      <Link href={`/jobs/${j.id}`}>통계 리포트 열기</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
