import type { JobRow, NotificationRow } from "@/lib/api";
import {
  buildDemoReport,
  createInitialJobs,
  createInitialNotifications,
  initialQueueStats,
} from "@/lib/mock/fixtures";

type DemoStore = {
  jobs: JobRow[];
  reports: Map<number, Record<string, unknown>>;
  notifications: NotificationRow[];
  nextJobId: number;
  nextNotificationId: number;
  runningStartedAt: Map<number, number>;
};

const globalKey = "__nemotron_demo_store__";

function getGlobalStore(): DemoStore {
  const g = globalThis as typeof globalThis & { [globalKey]?: DemoStore };
  if (!g[globalKey]) {
    const jobs = createInitialJobs();
    const reports = new Map<number, Record<string, unknown>>();
    reports.set(901, buildDemoReport(901));
    g[globalKey] = {
      jobs,
      reports,
      notifications: createInitialNotifications(),
      nextJobId: 905,
      nextNotificationId: 5,
      runningStartedAt: new Map([[902, Date.now() - 95_000]]),
    };
  }
  return g[globalKey]!;
}

export function getDemoStore(): DemoStore {
  return getGlobalStore();
}

export function resetDemoStore(): void {
  const g = globalThis as typeof globalThis & { [globalKey]?: DemoStore };
  delete g[globalKey];
}

/** 진행 중 작업(#902 등) 진행률을 요청마다 조금씩 올립니다. */
export function tickRunningJobs(store: DemoStore): void {
  for (const job of store.jobs) {
    if (job.status !== "running" || !job.progress) continue;
    const p = job.progress;
    const total = p.tasks.total || 24;
    let completed = p.tasks.completed;
    if (completed < total - 2 && Math.random() > 0.35) {
      completed += 1;
    }
    const pending = Math.max(0, total - completed - p.tasks.running);
    const percent = Math.min(99, Math.round((completed / total) * 100));
    p.tasks = { ...p.tasks, completed, pending };
    p.percent = percent;
    p.elapsed_sec = (p.elapsed_sec ?? 0) + 3;
    p.eta_sec = Math.max(0, Math.round((total - completed) * (p.avg_sec_per_task ?? 7)));
  }
}

export function queueStatsFromJobs(jobs: JobRow[]) {
  return initialQueueStats(jobs);
}
