"use client";

import { isDemoMode, isStaticDemo } from "@/lib/demo-mode";

export function DemoBanner() {
  if (!isDemoMode()) return null;

  return (
    <div className="demo-banner" role="status" aria-live="polite">
      <span className="material-symbols-outlined demo-banner-icon" aria-hidden>
        science
      </span>
      <span>
        <strong>데모 모드</strong> — FastAPI·워커·Chroma 없이 목업 데이터로 UI를 미리볼 수 있습니다. 새 작업은
        약 5초 후 자동 완료됩니다.
        {isStaticDemo() ? " 정적 호스팅 — 변경 사항은 이 브라우저 탭에만 유지됩니다." : ""}
      </span>
    </div>
  );
}
