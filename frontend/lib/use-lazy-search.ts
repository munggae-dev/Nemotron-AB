"use client";

import { useCallback, useEffect, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

const DEFAULT_DELAY_MS = 400;

/**
 * 입력이 잠시 멈추거나(blur/Enter) 명시적으로 확정될 때만 query가 갱신됩니다.
 */
export function useLazySearch(delayMs: number = DEFAULT_DELAY_MS) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const inputRef = useRef(input);
  inputRef.current = input;

  const commit = useCallback((value?: string) => {
    setQuery((value ?? inputRef.current).trim());
  }, []);

  useEffect(() => {
    const trimmed = input.trim();
    const timer = window.setTimeout(() => {
      setQuery((prev) => (prev === trimmed ? prev : trimmed));
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [input, delayMs]);

  const clear = useCallback(() => {
    setInput("");
    setQuery("");
  }, []);

  return {
    input,
    setInput,
    query,
    commit,
    clear,
    onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commit();
      }
    },
    onBlur: (_e: FocusEvent<HTMLInputElement>) => {
      commit();
    },
  };
}
