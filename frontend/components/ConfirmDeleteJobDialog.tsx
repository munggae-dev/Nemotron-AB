"use client";

type ConfirmDeleteJobDialogProps = {
  job: { id: number; title?: string | null } | null;
  loading: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
};

export function ConfirmDeleteJobDialog({
  job,
  loading,
  error,
  onCancel,
  onConfirm,
}: ConfirmDeleteJobDialogProps) {
  if (!job) return null;

  const label = job.title || `작업 #${job.id}`;

  return (
    <div
      className="confirm-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="job-delete-dialog-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && !loading) onCancel();
      }}
    >
      <div className="confirm-modal">
        <h3 id="job-delete-dialog-title">작업 삭제</h3>
        <p className="confirm-modal-lede">
          <strong>{label}</strong>
          (ID #{job.id})을(를) 큐에서 제거합니다.
        </p>
        <p className="confirm-modal-warn">
          삭제 후에는 리포트·작업 기록·부분 결과·연결 알림을 복구할 수 없습니다. 계속하시겠습니까?
        </p>
        {error ? <div className="msg err">{error}</div> : null}
        <div className="confirm-modal-actions">
          <button type="button" className="btn secondary" disabled={loading} onClick={onCancel}>
            취소
          </button>
          <button type="button" className="btn btn--danger" disabled={loading} onClick={onConfirm}>
            {loading ? "삭제 중…" : "삭제"}
          </button>
        </div>
      </div>
    </div>
  );
}
