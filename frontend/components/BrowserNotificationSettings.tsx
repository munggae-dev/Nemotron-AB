"use client";

import { useCallback, useEffect, useState } from "react";
import {
  baselineLastNotifiedId,
  isBrowserNotificationSupported,
  isBrowserNotifyEnabled,
  requestBrowserNotificationPermission,
  setBrowserNotifyEnabled,
} from "@/lib/browser-notifications";
import { apiGet, type NotificationRow } from "@/lib/api";

function permissionLabel(p: NotificationPermission): string {
  if (p === "granted") return "허용됨";
  if (p === "denied") return "거부됨";
  return "미요청";
}

export function BrowserNotificationSettings() {
  const supported = isBrowserNotificationSupported();
  const [enabled, setEnabled] = useState(false);
  const [permission, setPermission] = useState<NotificationPermission>("default");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    setEnabled(isBrowserNotifyEnabled());
    if (supported) setPermission(Notification.permission);
  }, [supported]);

  const enable = useCallback(async () => {
    if (!supported) return;
    setBusy(true);
    setMsg(null);
    try {
      const perm = await requestBrowserNotificationPermission();
      setPermission(perm);
      if (perm !== "granted") {
        setEnabled(false);
        setBrowserNotifyEnabled(false);
        setMsg(
          perm === "denied"
            ? "브라우저에서 알림이 차단되어 있습니다. 주소창 옆 사이트 설정에서 알림을 허용해 주세요."
            : "알림 권한이 허용되지 않았습니다.",
        );
        return;
      }
      const rows = await apiGet<NotificationRow[]>("/notifications?limit=30");
      baselineLastNotifiedId(rows);
      setBrowserNotifyEnabled(true);
      setEnabled(true);
      setMsg("브라우저 알림이 켜졌습니다. 앱 탭이 열려 있는 동안 새 알림이 오면 표시됩니다.");
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [supported]);

  function disable() {
    setBrowserNotifyEnabled(false);
    setEnabled(false);
    setMsg("브라우저 알림을 껐습니다.");
  }

  if (!supported) {
    return (
      <div className="card browser-notify-settings">
        <p style={{ margin: 0, color: "var(--on-surface-variant)", fontSize: 14 }}>
          이 브라우저는 데스크톱 알림을 지원하지 않습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="card browser-notify-settings">
      <div className="browser-notify-settings-head">
        <span className="material-symbols-outlined" aria-hidden>
          notifications_active
        </span>
        <div>
          <strong>브라우저 알림</strong>
          <p className="browser-notify-settings-sub">
            작업 완료·실패 등 새 알림이 생기면 OS 알림으로 표시합니다. (앱 탭이 열려 있을 때)
          </p>
        </div>
      </div>
      <p className="browser-notify-settings-meta">
        권한: <strong>{permissionLabel(permission)}</strong>
        {enabled ? " · 사용 중" : ""}
      </p>
      {msg ? <p className="browser-notify-settings-msg">{msg}</p> : null}
      <div className="browser-notify-settings-actions">
        {!enabled ? (
          <button type="button" className="btn" disabled={busy} onClick={() => void enable()}>
            {busy ? "요청 중…" : "브라우저 알림 켜기"}
          </button>
        ) : (
          <button type="button" className="btn secondary" disabled={busy} onClick={disable}>
            끄기
          </button>
        )}
        {permission === "denied" && !enabled ? (
          <button type="button" className="btn secondary" disabled={busy} onClick={() => void enable()}>
            권한 다시 요청
          </button>
        ) : null}
      </div>
    </div>
  );
}
