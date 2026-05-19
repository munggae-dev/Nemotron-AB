"use client";

import { useEffect, useMemo, useState } from "react";
import type { KoreaRegions, MetaPersonaFilters, PersonaPopulationEstimate } from "@/lib/api";
import { apiGet, apiPost, apiUploadJobAsset, type JobRow } from "@/lib/api";

const DRAFT_STORAGE_KEY = "nemotron-new-job-draft-v9";

type VariantFields = {
  text: string;
  image_url: string;
  /** POST /jobs/assets 응답 staging 참조 */
  image_asset_ref: string | null;
};

function composeVariantText(v: VariantFields): string {
  return v.text.trim();
}

function imagePayloadFromVariant(v: VariantFields): { type: string; value: string } | undefined {
  const ref = v.image_asset_ref?.trim();
  if (ref) return { type: "asset_ref", value: ref };
  const url = v.image_url.trim();
  if (url) return { type: "url", value: url };
  return undefined;
}


const defaultVariant = (): VariantFields => ({
  text: "",
  image_url: "",
  image_asset_ref: null,
});

const defaultForm = {
  title: "신규 A/B 평가",
  variant_a: defaultVariant(),
  variant_b: defaultVariant(),
  context: "",
  profile: "small",
  evaluator: "openai",
  llm_base_url: "http://localhost:11434/v1",
  llm_model: "gemma4:e2b-it-q4_K_M",
  response_format_json: false,
  prompt_profile: "full" as "full" | "compact",
  max_persona_chars: 1500,
  max_context_chars: 4000,
  max_personas: 24,
  retrieval_k_per_bucket: 80,
  eval_concurrency: 2,
  seed: 42,
  max_reason_chars: 80,
  use_llm_task_queue: true,
  persona_filter: {
    sex: "all" as "all" | "남자" | "여자",
    age_min: 20,
    age_max: 50,
    province: "",
    district: "",
    marital_status: "",
    education_level: "",
    family_type: "",
    housing_type: "",
    military_status: "",
    occupation_contains: "",
  },
};

type FormState = typeof defaultForm;

function tryParseDraft(raw: string | null): Partial<FormState> | null {
  if (!raw) return null;
  try {
    const o = JSON.parse(raw) as Record<string, unknown>;
    if (!o || typeof o !== "object") return null;
    return o as Partial<FormState>;
  } catch {
    return null;
  }
}

export default function NewJobPage() {
  const [regions, setRegions] = useState<KoreaRegions | null>(null);
  const [personaMeta, setPersonaMeta] = useState<MetaPersonaFilters | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [draftLoaded, setDraftLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploadBusy, setUploadBusy] = useState<"a" | "b" | null>(null);
  const [populationEstimate, setPopulationEstimate] = useState<number | null>(null);
  const [populationLoading, setPopulationLoading] = useState(false);
  const [populationErr, setPopulationErr] = useState<string | null>(null);
  const [populationCapped, setPopulationCapped] = useState(false);
  const [prefillDone, setPrefillDone] = useState(false);
  const [fromJobId, setFromJobId] = useState<number | null>(null);
  const estimateFilter = useMemo(
    () => ({
      sex: form.persona_filter.sex,
      age_min: form.persona_filter.age_min,
      age_max: form.persona_filter.age_max,
      province: "",
      district: "",
      marital_status: "",
      education_level: "",
      family_type: "",
      housing_type: "",
      military_status: "",
      occupation_contains: "",
    }),
    [form.persona_filter.sex, form.persona_filter.age_min, form.persona_filter.age_max],
  );

  useEffect(() => {
    apiGet<KoreaRegions>("/meta/regions")
      .then(setRegions)
      .catch((e: Error) => setErr(e.message));
  }, []);

  useEffect(() => {
    apiGet<MetaPersonaFilters>("/meta/persona-filters")
      .then(setPersonaMeta)
      .catch(() => setPersonaMeta(null));
  }, []);

  useEffect(() => {
    const timer = setTimeout(async () => {
      setPopulationLoading(true);
      setPopulationErr(null);
      try {
        const res = await apiPost<PersonaPopulationEstimate>("/meta/persona-population-estimate", estimateFilter);
        setPopulationEstimate(res.count);
        setPopulationCapped(Boolean(res.capped));
      } catch (e: unknown) {
        setPopulationEstimate(null);
        setPopulationCapped(false);
        setPopulationErr(e instanceof Error ? e.message : String(e));
      } finally {
        setPopulationLoading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [estimateFilter]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const partial = tryParseDraft(localStorage.getItem(DRAFT_STORAGE_KEY));
    if (partial) {
      setForm((prev) => ({
        ...prev,
        ...partial,
        variant_a: partial.variant_a ?? prev.variant_a,
        variant_b: partial.variant_b ?? prev.variant_b,
        persona_filter: partial.persona_filter
          ? { ...defaultForm.persona_filter, ...partial.persona_filter }
          : prev.persona_filter,
      }));
    }
    setDraftLoaded(true);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    const raw = sp.get("fromJob");
    const id = raw ? Number(raw) : NaN;
    if (Number.isFinite(id) && id > 0) setFromJobId(id);
  }, []);

  useEffect(() => {
    if (!fromJobId || prefillDone) return;
    const id = fromJobId;
    if (!Number.isFinite(id)) {
      setPrefillDone(true);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const j = await apiGet<JobRow>(`/jobs/${id}`);
        if (cancelled) return;
        const payloadRaw = typeof j.payload_json === "string" ? JSON.parse(j.payload_json) : null;
        const payload = payloadRaw && typeof payloadRaw === "object" ? (payloadRaw as Record<string, unknown>) : null;
        if (!payload) {
          setErr("이전 작업 payload를 읽지 못했습니다.");
          setPrefillDone(true);
          return;
        }
        const pfRaw = payload.persona_filter;
        const personaFilter = pfRaw && typeof pfRaw === "object" ? (pfRaw as Record<string, unknown>) : {};
        const imageA = payload.image_a && typeof payload.image_a === "object" ? (payload.image_a as Record<string, unknown>) : null;
        const imageB = payload.image_b && typeof payload.image_b === "object" ? (payload.image_b as Record<string, unknown>) : null;
        const legacyContextParts = [
          String(payload.product ?? ""),
          String(payload.category ?? ""),
          String(payload.tone ?? ""),
          String(payload.goal ?? ""),
          String(payload.description ?? ""),
        ].filter((s) => s.trim());
        const inheritedContext = String(
          payload.context ?? (legacyContextParts.length ? legacyContextParts.join(" / ") : ""),
        );
        setForm({
          ...defaultForm,
          title: `${String(payload.title ?? j.title ?? "복제 작업")} (복제)`,
          variant_a: {
            ...defaultVariant(),
            text: String(payload.text_a ?? payload.copy_a ?? ""),
            image_url:
              imageA && String(imageA.type ?? "") === "url" ? String(imageA.value ?? "") : "",
            image_asset_ref:
              imageA && String(imageA.type ?? "") === "asset_ref" ? String(imageA.value ?? "") : null,
          },
          variant_b: {
            ...defaultVariant(),
            text: String(payload.text_b ?? payload.copy_b ?? ""),
            image_url:
              imageB && String(imageB.type ?? "") === "url" ? String(imageB.value ?? "") : "",
            image_asset_ref:
              imageB && String(imageB.type ?? "") === "asset_ref" ? String(imageB.value ?? "") : null,
          },
          context: inheritedContext,
          profile: String(payload.profile ?? defaultForm.profile),
          evaluator: String(payload.evaluator ?? defaultForm.evaluator),
          llm_base_url: String(
            payload.llm_base_url ??
            (typeof payload.ollama_base_url === "string"
              ? `${String(payload.ollama_base_url).replace(/\/$/, "")}/v1`
              : defaultForm.llm_base_url),
          ),
          llm_model: String(payload.llm_model ?? payload.ollama_model ?? defaultForm.llm_model),
          response_format_json:
            typeof payload.response_format_json === "boolean"
              ? payload.response_format_json
              : defaultForm.response_format_json,
          prompt_profile: ((): "full" | "compact" => {
            const v = String(payload.prompt_profile ?? "").toLowerCase();
            return v === "compact" ? "compact" : "full";
          })(),
          max_persona_chars: Number(payload.max_persona_chars ?? defaultForm.max_persona_chars),
          max_context_chars: Number(payload.max_context_chars ?? defaultForm.max_context_chars),
          max_personas: Number(payload.max_personas ?? defaultForm.max_personas),
          retrieval_k_per_bucket: Number(payload.retrieval_k_per_bucket ?? defaultForm.retrieval_k_per_bucket),
          eval_concurrency: Number(payload.eval_concurrency ?? defaultForm.eval_concurrency),
          seed: Number(payload.seed ?? defaultForm.seed),
          max_reason_chars: Number(payload.max_reason_chars ?? defaultForm.max_reason_chars),
          use_llm_task_queue:
            typeof payload.use_llm_task_queue === "boolean"
              ? payload.use_llm_task_queue
              : defaultForm.use_llm_task_queue,
          persona_filter: {
            ...defaultForm.persona_filter,
            sex: String(personaFilter.sex ?? defaultForm.persona_filter.sex) as FormState["persona_filter"]["sex"],
            age_min: Number(personaFilter.age_min ?? defaultForm.persona_filter.age_min),
            age_max: Number(personaFilter.age_max ?? defaultForm.persona_filter.age_max),
            province: String(personaFilter.province ?? ""),
            district: String(personaFilter.district ?? ""),
            marital_status: String(personaFilter.marital_status ?? ""),
            education_level: String(personaFilter.education_level ?? ""),
            family_type: String(personaFilter.family_type ?? ""),
            housing_type: String(personaFilter.housing_type ?? ""),
            military_status: String(personaFilter.military_status ?? ""),
            occupation_contains: String(personaFilter.occupation_contains ?? ""),
          },
        });
        setOk(`작업 #${id} 설정을 불러왔습니다. 수정 후 다시 실행하세요.`);
      } catch (e: unknown) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setPrefillDone(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fromJobId, prefillDone]);

  const provinces = useMemo(() => (regions ? Object.keys(regions) : ["전체"]), [regions]);
  const provinceKey = form.persona_filter.province || "전체";
  const districtOptions = useMemo(() => {
    if (!regions) return ["전체"];
    return regions[provinceKey] || ["전체"];
  }, [regions, provinceKey]);
  function saveDraft() {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(form));
      setOk("임시 저장했습니다. 브라우저에 초안이 보관됩니다.");
      setErr(null);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "임시 저장에 실패했습니다.");
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setOk(null);
    const text_a = composeVariantText(form.variant_a);
    const text_b = composeVariantText(form.variant_b);
    const img_a = imagePayloadFromVariant(form.variant_a);
    const img_b = imagePayloadFromVariant(form.variant_b);
    if ((!text_a && !img_a) || (!text_b && !img_b)) {
      setErr("각 변형마다 텍스트 또는 이미지(URL/파일 업로드) 중 하나 이상 필요합니다.");
      return;
    }
    if (form.persona_filter.age_min > form.persona_filter.age_max) {
      setErr("나이 범위가 올바르지 않습니다.");
      return;
    }
    setLoading(true);
    try {
      const { variant_a: _va, variant_b: _vb, ...jobPayload } = form;
      const body: Record<string, unknown> = {
        ...jobPayload,
        text_a,
        text_b,
        persona_filter: {
          ...form.persona_filter,
          province: form.persona_filter.province === "전체" ? "" : form.persona_filter.province,
          district: form.persona_filter.district === "전체" ? "" : form.persona_filter.district,
        },
      };
      if (img_a) body.image_a = img_a;
      if (img_b) body.image_b = img_b;
      const res = await apiPost<{ id: number }>("/jobs", body);
      setOk(
        `작업 #${res.id}이(가) 접수되었습니다. 페르소나 매칭(벡터 검색)은 서버에서 진행되며, 잠시 후 작업 큐에서 매칭 중 → 대기 상태로 바뀝니다.`,
      );
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const updateVariant = (which: "variant_a" | "variant_b", patch: Partial<VariantFields>) => {
    setForm((prev) => ({
      ...prev,
      [which]: { ...prev[which], ...patch },
    }));
  };

  return (
    <form id="new-job" onSubmit={onSubmit}>
      <div className="page-header">
        <div>
          <h1 className="h1">테스트 설정 — 단문 · 이미지 A/B</h1>
          <p className="lede">
            안 A 와 안 B 를 텍스트·이미지로 구성합니다. 변형마다 텍스트만, 이미지만, 또는 둘 다 넣을 수 있습니다.
          </p>
        </div>
      </div>

      <div className="split-grid" style={{ marginBottom: 24 }}>
        <div className="split-panel">
          <div className="split-panel-header">
            <span className="tag">Variant A (컨트롤)</span>
            <span className="variant-chip variant-chip--success">
              <span className="material-symbols-outlined" style={{ fontVariationSettings: '"FILL" 1' }}>
                trending_up
              </span>
              기준 안
            </span>
          </div>
          <div className="split-panel-inner">
            <div className="split-panel-fields">
              <div>
                <label className="field-label-human" htmlFor="va-text">
                  텍스트
                </label>
                <textarea
                  id="va-text"
                  rows={6}
                  value={form.variant_a.text}
                  onChange={(e) => updateVariant("variant_a", { text: e.target.value })}
                  placeholder="평가 대상 단문을 입력하세요. 헤드라인·본문·CTA 가 한 변형에 모두 포함되어 있다면 줄바꿈으로 구분해도 됩니다. (예: 제품 설명, 공지 문구, UI 카피, 광고 카피 등)"
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="va-img-url">
                  이미지 URL (선택)
                </label>
                <input
                  id="va-img-url"
                  type="url"
                  inputMode="url"
                  value={form.variant_a.image_url}
                  onChange={(e) =>
                    updateVariant("variant_a", { image_url: e.target.value, image_asset_ref: null })
                  }
                  placeholder="https://..."
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="va-img-file">
                  이미지 파일 (선택)
                </label>
                <input
                  id="va-img-file"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  disabled={uploadBusy !== null}
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (!f) return;
                    setUploadBusy("a");
                    setErr(null);
                    try {
                      const { asset_ref } = await apiUploadJobAsset(f);
                      updateVariant("variant_a", { image_asset_ref: asset_ref, image_url: "" });
                    } catch (ex: unknown) {
                      setErr(ex instanceof Error ? ex.message : String(ex));
                    } finally {
                      setUploadBusy(null);
                    }
                  }}
                />
                {uploadBusy === "a" ? <p className="muted small">업로드 중…</p> : null}
                {form.variant_a.image_asset_ref ? (
                  <p className="muted small">
                    <span className="material-symbols-outlined" style={{ fontSize: "1rem", verticalAlign: "middle" }}>
                      cloud_upload
                    </span>{" "}
                    이미지 파일이 첨부되었습니다.
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <div className="split-panel">
          <div className="split-panel-header split-panel-header--challenger">
            <span className="tag">Variant B (챌린저)</span>
            <span className="variant-chip variant-chip--hypothesis">
              <span className="material-symbols-outlined">science</span>
              비교 · 가설 검증
            </span>
          </div>
          <div className="split-panel-inner">
            <div className="split-panel-fields">
              <div>
                <label className="field-label-human" htmlFor="vb-text">
                  텍스트
                </label>
                <textarea
                  id="vb-text"
                  className="input-variant-b"
                  rows={6}
                  value={form.variant_b.text}
                  onChange={(e) => updateVariant("variant_b", { text: e.target.value })}
                  placeholder="비교군 단문을 입력하세요. 헤드라인·본문·CTA 가 한 변형에 모두 포함되어 있다면 줄바꿈으로 구분해도 됩니다."
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="vb-img-url">
                  이미지 URL (선택)
                </label>
                <input
                  id="vb-img-url"
                  className="input-variant-b"
                  type="url"
                  inputMode="url"
                  value={form.variant_b.image_url}
                  onChange={(e) =>
                    updateVariant("variant_b", { image_url: e.target.value, image_asset_ref: null })
                  }
                  placeholder="https://..."
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="vb-img-file">
                  이미지 파일 (선택)
                </label>
                <input
                  id="vb-img-file"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  disabled={uploadBusy !== null}
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (!f) return;
                    setUploadBusy("b");
                    setErr(null);
                    try {
                      const { asset_ref } = await apiUploadJobAsset(f);
                      updateVariant("variant_b", { image_asset_ref: asset_ref, image_url: "" });
                    } catch (ex: unknown) {
                      setErr(ex instanceof Error ? ex.message : String(ex));
                    } finally {
                      setUploadBusy(null);
                    }
                  }}
                />
                {uploadBusy === "b" ? <p className="muted small">업로드 중…</p> : null}
                {form.variant_b.image_asset_ref ? (
                  <p className="muted small">
                    <span className="material-symbols-outlined" style={{ fontSize: "1rem", verticalAlign: "middle" }}>
                      cloud_upload
                    </span>{" "}
                    이미지 파일이 첨부되었습니다.
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="targeting-card">
        <div className="targeting-card-head">
          <span className="material-symbols-outlined" aria-hidden>
            target
          </span>
          <div>
            <h4>타깃팅 · 페르소나 필터</h4>
            <p className="nemotron-targeting-sub muted">
              인구통계·가구 필드 값은 Nvidia{" "}
              <a href="https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea" target="_blank" rel="noreferrer">
                Nemotron-Personas-Korea
              </a>{" "}
              데이터와 동일한 라벨을 사용합니다 (벡터DB 재빌드 후 적용).
            </p>
            {personaMeta?.vectordb_hint ? <p className="nemotron-targeting-sub muted">{personaMeta.vectordb_hint}</p> : null}
          </div>
        </div>
        <div className="msg" style={{ marginBottom: 14 }}>
          {populationLoading ? (
            <span className="muted">예상 모수 계산 중…</span>
          ) : populationErr ? (
            <span className="muted">예상 모수를 불러오지 못했습니다.</span>
          ) : (
            <span>
              예상 모수{" "}
              <strong>
                {populationEstimate !== null
                  ? `${populationEstimate.toLocaleString()}${populationCapped ? "+" : ""}`
                  : "-"}
              </strong>{" "}
              명
              {populationCapped ? " (빠른 추정 하한)" : ""}
              {populationEstimate !== null && populationEstimate < form.max_personas
                ? " · 현재 최대 페르소나보다 적어 표본이 부족할 수 있습니다."
                : ""}
            </span>
          )}
        </div>
        <div className="logic-rule-row">
          <span className="logic-badge-if">IF</span>
          <div className="logic-rule-grow">
            <span className="field-label-human" style={{ marginBottom: 0, flex: "0 0 auto" }}>
              성별
            </span>
            <select
              className="logic-select-op"
              aria-label="연산자"
              disabled
              value="equals"
            >
              <option value="equals">일치</option>
            </select>
            <select
              value={form.persona_filter.sex}
              onChange={(e) =>
                setForm({
                  ...form,
                  persona_filter: {
                    ...form.persona_filter,
                    sex: e.target.value as FormState["persona_filter"]["sex"],
                  },
                })
              }
            >
              <option value="all">전체</option>
              <option value="남자">남자</option>
              <option value="여자">여자</option>
            </select>
          </div>
        </div>
        <div className="logic-rule-row">
          <span className="logic-badge-if">IF</span>
          <div className="logic-rule-grow">
            <span className="field-label-human" style={{ marginBottom: 0, flex: "0 0 auto" }}>
              나이
            </span>
            <select className="logic-select-op" aria-label="연산자" disabled value="between">
              <option value="between">범위</option>
            </select>
            <input
              type="number"
              min={19}
              max={59}
              value={form.persona_filter.age_min}
              onChange={(e) =>
                setForm({
                  ...form,
                  persona_filter: { ...form.persona_filter, age_min: Number(e.target.value) },
                })
              }
            />
            <span style={{ color: "var(--outline)" }}>—</span>
            <input
              type="number"
              min={19}
              max={59}
              value={form.persona_filter.age_max}
              onChange={(e) =>
                setForm({
                  ...form,
                  persona_filter: { ...form.persona_filter, age_max: Number(e.target.value) },
                })
              }
            />
          </div>
        </div>
        <div className="targeting-split" />

        <p className="field-label-human" style={{ marginBottom: 10 }}>
          Nemotron 카테고리 (선택 시에만 필터 적용)
        </p>
        {!personaMeta ? (
          <p className="muted small">필터 목록을 불러오는 중이거나 API에 연결되지 않았습니다.</p>
        ) : null}
        <div className="nemotron-filter-grid">
          {(personaMeta?.enum_fields ?? []).map((field) => (
            <div key={field.key}>
              <label className="field-label-human" htmlFor={`pf-${field.key}`}>
                {field.label}
              </label>
              <select
                id={`pf-${field.key}`}
                value={(() => {
                  const raw = (form.persona_filter as Record<string, unknown>)[field.key];
                  return typeof raw === "string" ? raw : "";
                })()}
                onChange={(e) =>
                  setForm({
                    ...form,
                    persona_filter: {
                      ...form.persona_filter,
                      [field.key]: e.target.value,
                    } as FormState["persona_filter"],
                  })
                }
              >
                <option value="">선택 안 함</option>
                {field.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 16 }}>
          <label className="field-label-human" htmlFor="pf-occupation">
            직업 키워드 (부분 일치)
          </label>
          <input
            id="pf-occupation"
            type="text"
            maxLength={personaMeta?.occupation_contains?.max_chars ?? 80}
            value={form.persona_filter.occupation_contains}
            onChange={(e) =>
              setForm({
                ...form,
                persona_filter: { ...form.persona_filter, occupation_contains: e.target.value },
              })
            }
            placeholder="예: 간호 / 판매 / 개발"
            autoComplete="off"
          />
          <small className="hint">데이터셋의 직업(occupation) 문자열에 포함되는 표본만 남깁니다.</small>
        </div>

        <div className="targeting-split" />
        <div className="nemotron-filter-grid">
          <div>
            <label className="field-label-human" htmlFor="pf-province">
              지역(시/도)
            </label>
            <select
              id="pf-province"
              value={form.persona_filter.province || "전체"}
              onChange={(e) =>
                setForm({
                  ...form,
                  persona_filter: {
                    ...form.persona_filter,
                    province: e.target.value === "전체" ? "" : e.target.value,
                    district: "",
                  },
                })
              }
            >
              {provinces.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label-human" htmlFor="pf-district">
              지역(시/군/구)
            </label>
            <select
              id="pf-district"
              value={form.persona_filter.district || "전체"}
              onChange={(e) =>
                setForm({
                  ...form,
                  persona_filter: {
                    ...form.persona_filter,
                    district: e.target.value === "전체" ? "" : e.target.value,
                  },
                })
              }
            >
              {districtOptions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <label>작업명</label>
        <input type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <small className="hint">작업 큐와 보고서에서 구분할 이름입니다.</small>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <p className="section-title" style={{ marginTop: 0 }}>
          맥락 설명
        </p>
        <label htmlFor="ab-context">무엇을 비교하는지, 어떤 상황·청중에 쓰이는지 자유롭게 적어주세요.</label>
        <textarea
          id="ab-context"
          rows={4}
          value={form.context}
          onChange={(e) => setForm({ ...form, context: e.target.value })}
          placeholder={"예시\n• 신규 가입 화면의 안내 문구 A/B\n• 사내 공지 알림 카피 A/B\n• 이너뷰티 젤리 광고 카피 A/B (30대 여성 타깃)"}
        />
        <small className="hint">
          이 텍스트가 LLM 프롬프트에 그대로 전달되어 페르소나가 안 A·안 B 를 어떤 맥락에서 비교해야 하는지 인지하게 됩니다.
        </small>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <p className="section-title" style={{ marginTop: 0 }}>
          실행 옵션
        </p>
        <div className="row cols-4">
          <div>
            <label>프로파일</label>
            <select value={form.profile} onChange={(e) => setForm({ ...form, profile: e.target.value })}>
              <option value="small">small</option>
              <option value="standard">standard</option>
            </select>
          </div>
          <div>
            <label>평가기</label>
            <select value={form.evaluator} onChange={(e) => setForm({ ...form, evaluator: e.target.value })}>
              <option value="openai">openai (OpenAI-호환)</option>
              <option value="mock">mock</option>
            </select>
          </div>
          <div>
            <label>최대 페르소나</label>
            <input
              type="number"
              min={8}
              max={200}
              value={form.max_personas}
              onChange={(e) => setForm({ ...form, max_personas: Number(e.target.value) })}
            />
          </div>
          <div>
            <label>평가 동시성</label>
            <input
              type="number"
              min={1}
              max={8}
              value={form.eval_concurrency}
              onChange={(e) => setForm({ ...form, eval_concurrency: Number(e.target.value) })}
            />
          </div>
        </div>
        <div className="field-label-with-help" style={{ marginTop: 14 }}>
          <label htmlFor="retrieval-k-per-bucket">버킷당 검색 수</label>
          <span className="field-help-wrap">
            <button
              type="button"
              className="field-help-btn"
              aria-label="버킷당 검색 수 설명 보기"
            >
              <span className="material-symbols-outlined" aria-hidden>
                help
              </span>
            </button>
            <div className="field-help-tooltip" role="tooltip">
              <p>
                <strong>버킷</strong>은 연령대 구간(20대·30대·40대·50대)입니다. 작업의 맥락·안 A·안 B
                텍스트와 <strong>의미가 비슷한</strong> 페르소나를 벡터 DB에서 찾을 때, 연령대마다 최대 이
                숫자만큼 후보를 가져옵니다.
              </p>
              <p>
                후보를 모은 뒤 <strong>최대 페르소나</strong> 수만큼만 골라 LLM 평가에 씁니다. 값을 크게 하면
                다양한 후보를 확보하기 쉽지만 검색·평가가 느려지고, 작게 하면 빠르지만 연령대별 후보가 부족할
                수 있습니다.
              </p>
              <p className="field-help-tooltip-note">
                기본 80 · 허용 20~500. API 필드명: <code className="mono">retrieval_k_per_bucket</code>
              </p>
            </div>
          </span>
        </div>
        <input
          id="retrieval-k-per-bucket"
          type="number"
          min={20}
          max={500}
          value={form.retrieval_k_per_bucket}
          onChange={(e) => setForm({ ...form, retrieval_k_per_bucket: Number(e.target.value) })}
        />
        <div className="check-row">
          <input
            type="checkbox"
            id="use_llm_task_queue"
            checked={form.use_llm_task_queue}
            onChange={(e) => setForm({ ...form, use_llm_task_queue: e.target.checked })}
          />
          <label htmlFor="use_llm_task_queue" style={{ marginBottom: 0, textTransform: "none", letterSpacing: "normal" }}>
            LLM 태스크 큐 사용 (페르소나별 LangChain 호출 단위)
          </label>
        </div>
      </div>

      {form.evaluator !== "mock" ? (
        <details className="card collapsible-advanced-card">
          <summary className="collapsible-advanced-summary">
            <span className="tag-advanced">고급</span>
            <span className="collapsible-advanced-title">LLM 제공자 (OpenAI-호환)</span>
            <span className="material-symbols-outlined collapsible-advanced-chevron" aria-hidden>
              expand_more
            </span>
          </summary>
          <div className="collapsible-advanced-body">
          <p className="muted small" style={{ marginTop: 0 }}>
            Ollama, OpenAI, OpenRouter, Together, vLLM, llama.cpp 서버 등 OpenAI-호환 엔드포인트를 모두 지원합니다.
            <br />
            <strong>API 키는 서버 환경변수 `LLM_API_KEY` 로만 설정합니다.</strong> 폼/DB에 키가 저장되지 않습니다.
          </p>
          <div className="row cols-2">
            <div>
              <label>Base URL</label>
              <input
                type="url"
                value={form.llm_base_url}
                onChange={(e) => setForm({ ...form, llm_base_url: e.target.value })}
                placeholder="예: http://localhost:11434/v1, https://api.openai.com/v1"
                autoComplete="off"
              />
              <small className="hint">비우면 서버 환경변수 `LLM_BASE_URL` 또는 기본값(localhost Ollama) 사용</small>
            </div>
            <div>
              <label>모델</label>
              <input
                type="text"
                value={form.llm_model}
                onChange={(e) => setForm({ ...form, llm_model: e.target.value })}
                placeholder="예: gpt-4o-mini, gemma4:e2b-it-q4_K_M, claude-via-proxy/..."
                autoComplete="off"
              />
              <small className="hint">비우면 서버 환경변수 `LLM_MODEL` 또는 기본값 사용</small>
            </div>
          </div>
          <div className="check-row">
            <input
              type="checkbox"
              id="response_format_json"
              checked={form.response_format_json}
              onChange={(e) => setForm({ ...form, response_format_json: e.target.checked })}
              disabled={form.prompt_profile === "compact"}
            />
            <label htmlFor="response_format_json" style={{ marginBottom: 0, textTransform: "none", letterSpacing: "normal" }}>
              JSON 응답 강제 (`response_format`) — OpenAI 계열만 지원. 미지원 모델에서는 무시되거나 오류 가능.
              {form.prompt_profile === "compact" ? (
                <span className="muted small"> · compact 프로파일에서는 자동으로 켜집니다.</span>
              ) : null}
            </label>
          </div>

          <div className="row cols-3" style={{ marginTop: 16 }}>
            <div>
              <label>프롬프트 프로파일</label>
              <select
                value={form.prompt_profile}
                onChange={(e) => setForm({ ...form, prompt_profile: e.target.value as "full" | "compact" })}
              >
                <option value="full">full — 페르소나 raw, 사용자 설정 우선</option>
                <option value="compact">compact — 핵심 필드만 (토큰 절감)</option>
              </select>
              <small className="hint">
                compact 는 페르소나를 age/sex/occupation/province/district 로 축약하고 reason 길이를 40자로 캡, JSON 강제.
              </small>
            </div>
            <div>
              <label>페르소나 길이 상한 (max_persona_chars)</label>
              <input
                type="number"
                min={200}
                max={10000}
                step={100}
                value={form.max_persona_chars}
                onChange={(e) => setForm({ ...form, max_persona_chars: Number(e.target.value) })}
              />
              <small className="hint">프롬프트에 들어가는 페르소나 JSON 문자열 상한.</small>
            </div>
            <div>
              <label>입력 누적 길이 상한 (max_context_chars)</label>
              <input
                type="number"
                min={100}
                max={20000}
                step={100}
                value={form.max_context_chars}
                onChange={(e) => setForm({ ...form, max_context_chars: Number(e.target.value) })}
              />
              <small className="hint">text_a + text_b + context 누적 길이가 이 값을 넘으면 거절.</small>
            </div>
          </div>
          </div>
        </details>
      ) : null}

      <div className="form-submit-footer" aria-live="polite">
        {(err || ok) && (
          <div className="form-submit-footer-messages">
            {err ? <div className="msg err">{err}</div> : null}
            {ok ? <div className="msg ok">{ok}</div> : null}
          </div>
        )}
        <div className="form-submit-footer-actions">
          <button type="button" className="btn secondary" onClick={saveDraft} disabled={!draftLoaded}>
            임시 저장
          </button>
          <button type="submit" className="btn" disabled={loading || !regions}>
            {loading ? "등록 중…" : "검증 실행"}
          </button>
        </div>
      </div>
    </form>
  );
}
