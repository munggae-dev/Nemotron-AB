"use client";

import type { FocusEventHandler, KeyboardEventHandler } from "react";

type JobsSearchFieldProps = {
  value: string;
  onChange: (value: string) => void;
  onKeyDown?: KeyboardEventHandler<HTMLInputElement>;
  onBlur?: FocusEventHandler<HTMLInputElement>;
  placeholder?: string;
  ariaLabel?: string;
  showClear?: boolean;
  onClear?: () => void;
};

export function JobsSearchField({
  value,
  onChange,
  onKeyDown,
  onBlur,
  placeholder = "작업명 또는 ID 검색",
  ariaLabel = "작업 검색",
  showClear,
  onClear,
}: JobsSearchFieldProps) {
  return (
    <>
      <label className="jobs-search-field">
        <span className="material-symbols-outlined" aria-hidden>
          search
        </span>
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onBlur}
          placeholder={placeholder}
          aria-label={ariaLabel}
        />
      </label>
      {showClear ? (
        <button type="button" className="btn secondary jobs-search-clear" onClick={onClear}>
          검색 초기화
        </button>
      ) : null}
    </>
  );
}
