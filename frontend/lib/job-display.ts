const JOB_DELETABLE_STATUSES = new Set(["failed", "completed"]);

export function isJobDeletable(status: string): boolean {
  return JOB_DELETABLE_STATUSES.has(status);
}

export function statusPill(status: string): { cls: string; label: string } {
  if (status === "completed") return { cls: "status-pill status-pill--completed", label: "완료" };
  if (status === "failed") return { cls: "status-pill status-pill--failed", label: "실패" };
  if (status === "running") return { cls: "status-pill status-pill--running", label: "실행 중" };
  if (status === "preparing")
    return { cls: "status-pill status-pill--preparing", label: "매칭 중" };
  return { cls: "status-pill status-pill--pending", label: "대기" };
}

export function formatReportDuration(sec?: number): string {
  if (typeof sec !== "number" || !Number.isFinite(sec) || sec < 0) return "—";
  if (sec < 60) return `${sec.toFixed(1)}초`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}분 ${s}초`;
}

export function formatWhen(iso: string): string {
  try {
    const d = new Date(iso.replace(" ", "T"));
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}
