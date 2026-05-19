import type {
  JobRow,
  KoreaRegions,
  MetaPersonaFilters,
  NotificationRow,
  PersonaEvalRow,
  QueueStats,
} from "@/lib/api";

const now = Date.now();
const iso = (offsetMs: number) => new Date(now + offsetMs).toISOString();

export const DEMO_IMAGE_A = "https://picsum.photos/seed/nemotron-demo-a/720/480";
export const DEMO_IMAGE_B = "https://picsum.photos/seed/nemotron-demo-b/720/480";

export const DEMO_REGIONS: KoreaRegions = {
  전체: ["전체"],
  서울특별시: ["전체", "강남구", "서초구", "마포구", "송파구"],
  경기도: ["전체", "성남시", "수원시", "용인시"],
  부산광역시: ["전체", "해운대구", "부산진구"],
};

export const DEMO_PERSONA_FILTERS: MetaPersonaFilters = {
  dataset: "nvidia/Nemotron-Personas-Korea (데모)",
  age_range_note: "데모 모드 — 실제 벡터 DB 없이 UI만 동작합니다.",
  enum_fields: [
    {
      key: "marital_status",
      label: "혼인 상태",
      options: [
        { value: "", label: "(전체)" },
        { value: "미혼", label: "미혼" },
        { value: "배우자있음", label: "배우자있음" },
      ],
    },
    {
      key: "education_level",
      label: "학력",
      options: [
        { value: "", label: "(전체)" },
        { value: "4년제 대학교", label: "4년제 대학교" },
        { value: "대학원", label: "대학원" },
      ],
    },
  ],
  occupation_contains: { max_chars: 80 },
  vectordb_hint: "데모 모드에서는 페르소나 모수·검색이 고정 샘플 값으로 표시됩니다.",
};

export const DEMO_PERSONA_ROWS: PersonaEvalRow[] = [
  {
    persona_id: "demo-p-20-1",
    age: 24,
    bucket: "20s",
    winner: "B",
    weighted_score: { A: 62, B: 71 },
    confidence: 0.09,
    reason: "짧은 카피에서 혜택이 먼저 보이는 안 B가 클릭 의도가 더 높게 나왔습니다.",
  },
  {
    persona_id: "demo-p-20-2",
    age: 27,
    bucket: "20s",
    winner: "A",
    weighted_score: { A: 68, B: 64 },
    confidence: 0.04,
    reason: "브랜드 톤이 익숙한 안 A가 신뢰 지표에서 소폭 우세합니다.",
  },
  {
    persona_id: "demo-p-30-1",
    age: 34,
    bucket: "30s",
    winner: "B",
    weighted_score: { A: 58, B: 74 },
    confidence: 0.16,
    reason: "가격·혜택 강조 문구가 실질 구매 의도와 맞물려 안 B가 두드러집니다.",
  },
  {
    persona_id: "demo-p-30-2",
    age: 38,
    bucket: "30s",
    winner: "B",
    weighted_score: { A: 55, B: 69 },
    confidence: 0.14,
    reason: "업무 시간대 알림 맥락에서 행동 유도 문장이 더 명확합니다.",
  },
  {
    persona_id: "demo-p-40-1",
    age: 45,
    bucket: "40s",
    winner: "A",
    weighted_score: { A: 66, B: 61 },
    confidence: 0.05,
    reason: "과장 표현이 적은 안 A가 신뢰·안정감 면에서 선호됩니다.",
  },
  {
    persona_id: "demo-p-50-1",
    age: 52,
    bucket: "50s",
    winner: "B",
    weighted_score: { A: 59, B: 63 },
    confidence: 0.04,
    reason: "핵심 혜택 요약이 한눈에 들어와 안 B가 관심도에서 앞섭니다.",
  },
];

function completedPayload() {
  return {
    context: "모바일 앱 푸시 알림 — 주말 한정 프로모션",
    text_a: "이번 주말만! 전 상품 15% 할인 쿠폰이 도착했어요.",
    text_b: "주말 특가 🎁 지금 바로 쿠폰 받고 15% 할인 적용하기",
    image_a: { type: "url", value: DEMO_IMAGE_A },
    image_b: { type: "url", value: DEMO_IMAGE_B },
    evaluator: "mock",
    max_personas: 48,
    retrieval_k_per_bucket: 12,
    persona_filter: {
      sex: "all",
      age_min: 22,
      age_max: 54,
      province: "서울특별시",
      district: "전체",
    },
    llm_base_url: "http://localhost:11434/v1",
    llm_model: "gemma-demo",
  };
}

export function buildDemoReport(jobId: number) {
  return {
    campaign_id: `job_${jobId}`,
    campaign: {
      context: "모바일 앱 푸시 알림 — 주말 한정 프로모션",
      text_a: "이번 주말만! 전 상품 15% 할인 쿠폰이 도착했어요.",
      text_b: "주말 특가 🎁 지금 바로 쿠폰 받고 15% 할인 적용하기",
    },
    report: {
      final_winner: "B",
      overall: {
        count: 48,
        win_rate: { A: 0.375, B: 0.625 },
        avg_score: { A: 61.2, B: 67.8 },
        avg_confidence: 0.11,
      },
      summary_by_bucket: {
        "20s": {
          count: 12,
          win_rate: { A: 0.42, B: 0.58 },
          avg_score: { A: 63.1, B: 68.4 },
          avg_confidence: 0.08,
        },
        "30s": {
          count: 14,
          win_rate: { A: 0.29, B: 0.71 },
          avg_score: { A: 58.5, B: 71.2 },
          avg_confidence: 0.14,
        },
        "40s": {
          count: 11,
          win_rate: { A: 0.45, B: 0.55 },
          avg_score: { A: 62.8, B: 64.1 },
          avg_confidence: 0.09,
        },
        "50s": {
          count: 11,
          win_rate: { A: 0.36, B: 0.64 },
          avg_score: { A: 60.4, B: 65.9 },
          avg_confidence: 0.1,
        },
      },
      key_reasons: [
        "30대에서 안 B의 행동 유도 문구가 클릭·구매 의도를 끌어올렸습니다.",
        "20대는 혜택 강조(B)와 톤 안정감(A)이 엇갈려 세그먼트별 메시지 분리가 유효해 보입니다.",
        "전체 평균 가중 점수·승률 기준 최종 추천은 Variant B입니다.",
      ],
      conditional_recommendation: [
        {
          bucket: "20s",
          suggested: "A",
          note: "신뢰·브랜드 톤이 더 중요한 코호트",
        },
      ],
    },
    funnel: {
      persona_filter: completedPayload().persona_filter,
      flow: { selected_personas: 48, scored_personas: 48, failed_personas: 0 },
    },
    runtime: { elapsed_sec: 142 },
    tokens: {
      prompt_tokens: 62400,
      completion_tokens: 18240,
      total_tokens: 80640,
      task_count: 48,
      eval_call_count: 48,
      synthesis_call_count: 1,
      eval_total_tokens: 79800,
      synthesis_total_tokens: 840,
    },
    synthesis: {
      generated_at: iso(-60_000),
      model: "demo-synthesis",
      base_url: "http://localhost:11434/v1",
      base_url_host: "localhost:11434",
      multimodal: true,
      tokens: { prompt_tokens: 520, completion_tokens: 320, total_tokens: 840 },
      content: {
        headline: "30대 중심으로 안 B가 우세 — 20대는 톤 분리 검토",
        executive_summary:
          "48명 페르소나 시뮬레이션 결과, 안 B(이모지·즉시 행동 CTA)가 전체 승률 62.5%로 승리했습니다. 30대에서 격차가 가장 크며, 20대는 신뢰 톤의 안 A가 일부 회수했습니다.",
        segment_notes:
          "푸시 알림 맥락에서는 짧은 혜택 요약 + 행동 버튼 문구가 반응을 높였습니다. 40대 이상은 과장 표현에 민감해 안 A가 신뢰 지표에서 방어적 우위를 보였습니다.",
        action_items: [
          "기본안으로 B 채택, 20대 코호트에는 A 톤 변형 A/B 재검증",
          "이모지 사용은 30대 이하에 한정해 40대+ 세그먼트 별도 카피 검토",
        ],
        limitations: "데모 데이터 — 실제 Nemotron 페르소나·LLM 호출 없이 생성된 샘플입니다.",
        full_markdown:
          "## 종합\n\n- **최종 추천: B**\n- 30대 클릭·구매 의도 +8%p 수준 (데모)\n- 20대는 신뢰 톤 분리 권장",
      },
      inputs_used: {
        context: completedPayload().context,
        text_a: completedPayload().text_a,
        text_b: completedPayload().text_b,
        multimodal: true,
        persona_evaluations: DEMO_PERSONA_ROWS,
        persona_evaluations_meta: {
          total_rows: 48,
          included_rows: 6,
          truncated: true,
        },
      },
    },
  };
}

export function createInitialJobs(): JobRow[] {
  const completedSummary = {
    final_winner: "B",
    overall: {
      count: 48,
      win_rate: { A: 0.375, B: 0.625 },
      avg_score: { A: 61.2, B: 67.8 },
      avg_confidence: 0.11,
    },
    key_reasons: [
      "30대에서 안 B의 행동 유도 문구가 클릭·구매 의도를 끌어올렸습니다.",
      "전체 평균 가중 점수·승률 기준 최종 추천은 Variant B입니다.",
    ],
    runtime: { elapsed_sec: 142 },
    tokens: {
      prompt_tokens: 62400,
      completion_tokens: 18240,
      total_tokens: 80640,
      task_count: 48,
    },
    synthesis_headline: "30대 중심으로 안 B가 우세 — 20대는 톤 분리 검토",
    synthesis_generated_at: iso(-60_000),
    synthesis_model: "demo-synthesis",
  };

  return [
    {
      id: 901,
      title: "[데모] 주말 푸시 알림 A/B — 텍스트+이미지",
      status: "completed",
      created_at: iso(-7200_000),
      started_at: iso(-7100_000),
      finished_at: iso(-6800_000),
      payload_json: JSON.stringify(completedPayload()),
      report_summary: completedSummary,
    },
    {
      id: 902,
      title: "[데모] 랜딩 히어로 카피 검증 (진행 중)",
      status: "running",
      created_at: iso(-600_000),
      started_at: iso(-480_000),
      payload_json: JSON.stringify({
        context: "랜딩 페이지 히어로",
        text_a: "당신의 일상을 더 가볍게",
        text_b: "3분이면 끝나는 스마트 루틴",
        evaluator: "mock",
        max_personas: 24,
        retrieval_k_per_bucket: 6,
        persona_filter: { sex: "all", age_min: 25, age_max: 45 },
      }),
      progress: {
        phase: "evaluating",
        label: "페르소나 평가",
        detail: "데모: 진행률이 자동으로 올라갑니다",
        tasks: { total: 24, pending: 8, running: 2, completed: 14, failed: 0 },
        percent: 58,
        elapsed_sec: 95,
        elapsed_since_created_sec: 120,
        avg_sec_per_task: 6.8,
        eta_sec: 68,
        eta_at: iso(68_000),
        note: null,
      },
    },
    {
      id: 903,
      title: "[데모] 앱 온보딩 문구 (대기)",
      status: "pending",
      created_at: iso(-120_000),
      payload_json: JSON.stringify({
        context: "온보딩 1단계",
        text_a: "시작하기",
        text_b: "3초 만에 시작",
        evaluator: "mock",
        max_personas: 16,
      }),
    },
    {
      id: 904,
      title: "[데모] 실패 예시 작업",
      status: "failed",
      created_at: iso(-3600_000),
      finished_at: iso(-3500_000),
      error_message: "데모: 워커 타임아웃 시뮬레이션",
      payload_json: JSON.stringify({
        context: "데모 실패 케이스",
        text_a: "A",
        text_b: "B",
        evaluator: "mock",
      }),
    },
  ];
}

export function createInitialNotifications(): NotificationRow[] {
  return [
    {
      id: 1,
      job_id: 901,
      type: "success",
      title: "작업 #901 완료",
      message: "리포트가 생성되었습니다. 분석·보고서에서 확인하세요.",
      is_read: 0,
      created_at: iso(-6800_000),
    },
    {
      id: 2,
      job_id: 902,
      type: "info",
      title: "작업 #902 실행 중",
      message: "페르소나 평가가 진행 중입니다 (데모).",
      is_read: 0,
      created_at: iso(-300_000),
    },
    {
      id: 3,
      job_id: 903,
      type: "info",
      title: "작업 #903 등록",
      message: "큐에 추가되었습니다. 데모에서는 자동 실행되지 않습니다.",
      is_read: 1,
      created_at: iso(-120_000),
    },
    {
      id: 4,
      job_id: 904,
      type: "error",
      title: "작업 #904 실패",
      message: "데모: 워커 타임아웃 시뮬레이션",
      is_read: 1,
      created_at: iso(-3500_000),
    },
  ];
}

export function initialQueueStats(jobs: JobRow[]): QueueStats {
  const by_status: Record<string, number> = {};
  for (const j of jobs) {
    by_status[j.status] = (by_status[j.status] ?? 0) + 1;
  }
  return { total: jobs.length, by_status };
}
