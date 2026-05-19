"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ConfirmDeleteJobDialog } from "@/components/ConfirmDeleteJobDialog";
import { JobsSearchField } from "@/components/JobsSearchField";
import { apiDelete, apiGet, type JobRow, type JobsListPage } from "@/lib/api";
import { formatWhen, isJobDeletable, statusPill } from "@/lib/job-display";
import { useLazySearch } from "@/lib/use-lazy-search";

type JobsListPanelProps = {
  title?: string;
  pageSize?: number;
  statusFilter?: string;
  showCloneLink?: boolean;
  headerLink?: { href: string; label: string };
  emptyHint?: ReactNode;
  className?: string;
};

export function JobsListPanel({
  title = "최근 작업",
  pageSize = 10,
  statusFilter,
  showCloneLink = false,
  headerLink,
  emptyHint,
  className = "",
}: JobsListPanelProps) {
  const search = useLazySearch();
  const [page, setPage] = useState(1);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<JobRow | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  useEffect(() => {
    setPage(1);
  }, [search.query]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    const offset = (page - 1) * pageSize;
    const params = new URLSearchParams({
      omit_payload: "true",
      include_total: "true",
      limit: String(pageSize),
      offset: String(offset),
    });
    if (search.query) params.set("q", search.query);
    if (statusFilter) params.set("status", statusFilter);
    try {
      const data = await apiGet<JobsListPage>(`/jobs?${params.toString()}`);
      setJobs(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setJobs([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search.query, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = total === 0 ? 0 : Math.min(page * pageSize, total);

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleteErr(null);
    setDeleteLoading(true);
    try {
      await apiDelete<{ status: string; id: number }>(`/jobs/${pendingDelete.id}`);
      setPendingDelete(null);
      if (jobs.length === 1 && page > 1) {
        setPage((p) => Math.max(1, p - 1));
      } else {
        await load();
      }
    } catch (e: unknown) {
      setDeleteErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleteLoading(false);
    }
  }

  return (
    <div className={`panel-rounded jobs-list-panel${className ? ` ${className}` : ""}`}>
      <div className="panel-rounded-head">
        <h3>{title}</h3>
        {headerLink ? (
          <Link
            href={headerLink.href}
            className="topbar-icon-btn"
            style={{ fontSize: 12, fontWeight: 700, width: "auto", padding: "8px 12px", color: "var(--primary)" }}
          >
            {headerLink.label}
          </Link>
        ) : null}
      </div>

      <div className="jobs-list-toolbar">
        <JobsSearchField
          value={search.input}
          onChange={search.setInput}
          onKeyDown={search.onKeyDown}
          onBlur={search.onBlur}
          showClear={Boolean(search.query)}
          onClear={search.clear}
        />
      </div>

      {err ? <div className="msg err jobs-list-panel-err">{err}</div> : null}

      {!err && loading && jobs.length === 0 ? (
        <div className="jobs-list-panel-empty">불러오는 중…</div>
      ) : null}

      {!err && !loading && jobs.length === 0 ? (
        <div className="jobs-list-panel-empty">
          {search.query ? (
            <>
              검색 결과가 없습니다. <button type="button" className="btn-link" onClick={search.clear}>검색 초기화</button>
            </>
          ) : (
            emptyHint ?? (
              <>
                등록된 작업이 없습니다. <Link href="/jobs/new">새 검증</Link>으로 시작하세요.
              </>
            )
          )}
        </div>
      ) : null}

      {!err && jobs.length > 0 ? (
        <>
          <div className="jobs-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>작업명</th>
                  <th>상태</th>
                  <th>추천</th>
                  <th className="text-right">생성</th>
                  <th className="text-right">{showCloneLink ? "분석" : "열기"}</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => {
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
                          <span style={{ fontWeight: 700, color: "var(--primary)" }}>
                            Variant {j.report_summary.final_winner}
                          </span>
                        ) : (
                          <span style={{ color: "var(--outline)" }}>—</span>
                        )}
                      </td>
                      <td className="text-right mono-cell" style={{ whiteSpace: "nowrap", color: "var(--on-surface-variant)" }}>
                        {formatWhen(j.created_at)}
                      </td>
                      <td className="text-right">
                        <span className="jobs-row-actions">
                          {showCloneLink ? (
                            <>
                              <Link href={`/jobs/${j.id}`}>{j.status === "completed" ? "리포트 열기" : "상세"}</Link>
                              <Link href={`/jobs/new?fromJob=${j.id}`} className="jobs-row-action-muted">
                                복제·수정
                              </Link>
                            </>
                          ) : (
                            <Link href={`/jobs/${j.id}`}>{j.status === "completed" ? "리포트" : "상세"}</Link>
                          )}
                          {isJobDeletable(j.status) ? (
                            <button
                              type="button"
                              className="btn-link btn-link--danger"
                              onClick={() => {
                                setDeleteErr(null);
                                setPendingDelete(j);
                              }}
                            >
                              삭제
                            </button>
                          ) : null}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="jobs-pagination" aria-label="작업 목록 페이지">
            <p className="jobs-pagination-summary">
              {total > 0 ? (
                <>
                  {rangeStart}–{rangeEnd} / 전체 {total}건
                  {search.query ? ` · 검색: “${search.query}”` : null}
                </>
              ) : (
                "0건"
              )}
            </p>
            <div className="jobs-pagination-actions">
              <button
                type="button"
                className="btn secondary"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                이전
              </button>
              <span className="jobs-pagination-page">
                {page} / {totalPages}
              </span>
              <button
                type="button"
                className="btn secondary"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                다음
              </button>
            </div>
          </div>
        </>
      ) : null}

      <ConfirmDeleteJobDialog
        job={pendingDelete}
        loading={deleteLoading}
        error={deleteErr}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
