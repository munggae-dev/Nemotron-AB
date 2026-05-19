import Link from "next/link";
import { CompletedReportsPanel } from "@/components/CompletedReportsPanel";

export default function ReportsIndexPage() {
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

      <CompletedReportsPanel />
    </>
  );
}
