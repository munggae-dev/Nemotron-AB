import Link from "next/link";

export default function HomePage() {
  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="h1">대시보드 개요</h1>
          <p className="lede">
            Nemotron 페르소나 기반 카피 A/B 검증입니다. 작업을 등록한 뒤 터미널에서{" "}
            <code className="mono">python -m app.worker_main</code> 워커를 실행하세요.
          </p>
        </div>
        <Link href="/jobs/new" className="btn" style={{ textAlign: "center" }}>
          새 검증 만들기
        </Link>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          gap: "16px",
          marginBottom: "24px",
        }}
      >
        <div className="card" style={{ marginBottom: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <span className="field-label" style={{ marginBottom: 8 }}>
              바로 가기
            </span>
            <span className="material-symbols-outlined" style={{ color: "var(--primary)" }}>
              bolt
            </span>
          </div>
          <p style={{ margin: 0, fontSize: 16, lineHeight: "24px", color: "var(--on-surface-variant)" }}>
            <Link href="/jobs/new">카피·필터 입력</Link> 후 큐에 등록합니다.
          </p>
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <span className="field-label" style={{ marginBottom: 8 }}>
              작업 큐
            </span>
            <span className="material-symbols-outlined" style={{ color: "var(--secondary)" }}>
              dashboard
            </span>
          </div>
          <p style={{ margin: 0, fontSize: 16, lineHeight: "24px", color: "var(--on-surface-variant)" }}>
            <Link href="/jobs">pending / running / 완료 상태</Link>를 확인합니다.
          </p>
        </div>
      </div>

      <div className="card">
        <h2 className="section-title" style={{ marginTop: 0 }}>
          시작 순서
        </h2>
        <ol style={{ margin: 0, paddingLeft: "1.25rem", color: "var(--on-surface-variant)", lineHeight: 1.7 }}>
          <li>
            <code className="mono">uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8010</code> 로 API 실행
          </li>
          <li>
            <code className="mono">NEXT_PUBLIC_API_BASE_URL</code> 이 API와 일치하는지 확인
          </li>
          <li>이 UI에서 작업 등록 → 워커 실행 → 알림·보고서 확인</li>
        </ol>
      </div>
    </>
  );
}
