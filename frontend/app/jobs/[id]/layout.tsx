import type { ReactNode } from "react";
import { DEMO_STATIC_JOB_IDS } from "@/lib/mock/static-params";

export function generateStaticParams() {
  if (process.env.NEXT_PUBLIC_DEMO_STATIC !== "1" && process.env.NEXT_PUBLIC_DEMO_STATIC !== "true") {
    return [];
  }
  return DEMO_STATIC_JOB_IDS.map((id) => ({ id: String(id) }));
}

export default function JobDetailLayout({ children }: { children: ReactNode }) {
  return children;
}
