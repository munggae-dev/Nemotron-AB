import { getApiBaseUrl } from "./api-base";
import { DEMO_IMAGE_A, DEMO_IMAGE_B } from "./mock/fixtures";
import { isInlineMockApi } from "./demo-mode";

/** 작업 변형 이미지 URL (정적 데모는 picsum, 그 외는 API 프록시). */
export function jobVariantImageUrl(jobId: number | string, variant: "a" | "b"): string {
  if (isInlineMockApi()) {
    return variant === "a" ? DEMO_IMAGE_A : DEMO_IMAGE_B;
  }
  return `${getApiBaseUrl()}/jobs/${jobId}/images/${variant}`;
}
