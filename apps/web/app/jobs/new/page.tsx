"use client";

import { useEffect, useMemo, useState } from "react";
import type { KoreaRegions, MetaPersonaFilters } from "@/lib/api";
import { apiGet, apiPost, apiUploadJobAsset } from "@/lib/api";

const DRAFT_STORAGE_KEY = "nemotron-new-job-draft-v6";

type VariantFields = {
  headline: string;
  body: string;
  cta: string;
  image_url: string;
  /** POST /jobs/assets 응답 staging 참조 */
  image_asset_ref: string | null;
};

function composeVariantCopy(v: VariantFields): string {
  return [v.headline, v.body, v.cta].map((s) => s.trim()).filter(Boolean).join("\n\n");
}

function variantHasVisual(variant: VariantFields): boolean {
  return Boolean(variant.image_url.trim() || variant.image_asset_ref);
}

function imagePayloadFromVariant(v: VariantFields): { type: string; value: string } | undefined {
  const ref = v.image_asset_ref?.trim();
  if (ref) return { type: "asset_ref", value: ref };
  const url = v.image_url.trim();
  if (url) return { type: "url", value: url };
  return undefined;
}

function VariantPreview({ variant, emptyLabel }: { variant: VariantFields; emptyLabel: string }) {
  const hasCopy = variant.headline.trim() || variant.body.trim() || variant.cta.trim();
  const hasVisual = variantHasVisual(variant);
  if (!hasCopy && !hasVisual) {
    return (
      <div className="preview-canvas preview-canvas--empty">
        <span className="material-symbols-outlined" aria-hidden>
          edit_note
        </span>
        <p>{emptyLabel}</p>
      </div>
    );
  }
  return (
    <div className="preview-canvas">
      {variant.image_url.trim() ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="preview-variant-img" src={variant.image_url.trim()} alt="" />
      ) : null}
      {variant.image_asset_ref ? (
        <div className="preview-asset-badge muted">
          <span className="material-symbols-outlined" style={{ fontSize: "1rem", verticalAlign: "middle" }}>
            cloud_upload
          </span>{" "}
          파일 업로드됨 (접수 후 미리보기 제공)
        </div>
      ) : null}
      {variant.headline.trim() ? <h4>{variant.headline}</h4> : null}
      {variant.body.trim() ? <p>{variant.body}</p> : null}
      {variant.cta.trim() ? (
        <button type="button" className="preview-cta">
          {variant.cta}
        </button>
      ) : null}
    </div>
  );
}

const defaultVariant = (): VariantFields => ({
  headline: "",
  body: "",
  cta: "",
  image_url: "",
  image_asset_ref: null,
});

const defaultForm = {
  title: "신규 카피 검증",
  variant_a: defaultVariant(),
  variant_b: defaultVariant(),
  product: "이너뷰티 젤리",
  category: "건강기능식품",
  tone: "밝고 자신감 있는 톤",
  goal: "신규 고객 유입",
  description: "",
  profile: "small",
  evaluator: "ollama",
  ollama_model: "gemma4:e4b-it-q4_K_M",
  ollama_base_url: "http://localhost:11434",
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
    const copy_a = composeVariantCopy(form.variant_a);
    const copy_b = composeVariantCopy(form.variant_b);
    const img_a = imagePayloadFromVariant(form.variant_a);
    const img_b = imagePayloadFromVariant(form.variant_b);
    if ((!copy_a && !img_a) || (!copy_b && !img_b)) {
      setErr("각 변형마다 카피(헤드라인·본문·CTA) 또는 이미지(URL/파일 업로드) 중 하나 이상 필요합니다.");
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
        copy_a,
        copy_b,
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
          <h1 className="h1">테스트 설정 — 카피 · 이미지 · 콘텐츠</h1>
          <p className="lede">
            컨트롤과 챌린저를 카피·이미지 A/B로 구성합니다. 변형마다 카피만, 이미지만, 또는 둘 다 넣을 수 있습니다.
          </p>
        </div>
        <div className="page-header-actions">
          <button type="button" className="btn secondary" onClick={saveDraft} disabled={!draftLoaded}>
            임시 저장
          </button>
          <button type="submit" className="btn" disabled={loading || !regions}>
            {loading ? "등록 중…" : "검증 실행"}
          </button>
        </div>
      </div>

      {err && <div className="msg err">{err}</div>}
      {ok && <div className="msg ok">{ok}</div>}

      <div className="split-grid" style={{ marginBottom: 24 }}>
        <div className="split-panel">
          <div className="split-panel-header">
            <span className="tag">Variant A (컨트롤)</span>
            <span className="variant-chip variant-chip--success">
              <span className="material-symbols-outlined" style={{ fontVariationSettings: '"FILL" 1' }}>
                trending_up
              </span>
              기준 카피
            </span>
          </div>
          <div className="split-panel-inner">
            <div className="split-panel-fields">
              <div>
                <label className="field-label-human" htmlFor="va-headline">
                  헤드라인
                </label>
                <input
                  id="va-headline"
                  type="text"
                  value={form.variant_a.headline}
                  onChange={(e) => updateVariant("variant_a", { headline: e.target.value })}
                  placeholder="예: 오늘부터 당신의 루틴을 바꿔보세요"
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="va-body">
                  본문 카피
                </label>
                <textarea
                  id="va-body"
                  rows={4}
                  value={form.variant_a.body}
                  onChange={(e) => updateVariant("variant_a", { body: e.target.value })}
                  placeholder="제품 혜택과 근거를 설명하는 문장을 입력하세요."
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="va-cta">
                  CTA 버튼 문구
                </label>
                <input
                  id="va-cta"
                  type="text"
                  value={form.variant_a.cta}
                  onChange={(e) => updateVariant("variant_a", { cta: e.target.value })}
                  placeholder="예: 무료 체험 신청"
                  autoComplete="off"
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
              </div>
            </div>
            <div className="preview-section">
              <span className="preview-section-label">미리보기</span>
              <VariantPreview
                variant={form.variant_a}
                emptyLabel="카피 또는 이미지를 입력하면 미리보기가 표시됩니다."
              />
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
                <label className="field-label-human" htmlFor="vb-headline">
                  헤드라인
                </label>
                <input
                  id="vb-headline"
                  className="input-variant-b"
                  type="text"
                  value={form.variant_b.headline}
                  onChange={(e) => updateVariant("variant_b", { headline: e.target.value })}
                  placeholder="챌린저 헤드라인"
                  autoComplete="off"
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="vb-body">
                  본문 카피
                </label>
                <textarea
                  id="vb-body"
                  className="input-variant-b"
                  rows={4}
                  value={form.variant_b.body}
                  onChange={(e) => updateVariant("variant_b", { body: e.target.value })}
                  placeholder="챌린저 본문을 입력하세요."
                />
              </div>
              <div>
                <label className="field-label-human" htmlFor="vb-cta">
                  CTA 버튼 문구
                </label>
                <input
                  id="vb-cta"
                  className="input-variant-b"
                  type="text"
                  value={form.variant_b.cta}
                  onChange={(e) => updateVariant("variant_b", { cta: e.target.value })}
                  placeholder="예: 지금 바로 알아보기"
                  autoComplete="off"
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
              </div>
            </div>
            <div className="preview-section">
              <span className="preview-section-label">미리보기</span>
              <VariantPreview
                variant={form.variant_b}
                emptyLabel="카피 또는 이미지를 입력하면 챌린저 미리보기가 표시됩니다."
              />
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
        <div className="logic-rule-row">
          <span className="logic-badge-if">IF</span>
          <div className="logic-rule-grow">
            <span className="field-label-human" style={{ marginBottom: 0, flex: "0 0 auto" }}>
              지역
            </span>
            <select className="logic-select-op" aria-label="연산자" disabled value="contains">
              <option value="contains">포함</option>
            </select>
            <select
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
            <select
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
                value={(form.persona_filter as Record<string, string>)[field.key] ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    persona_filter: { ...form.persona_filter, [field.key]: e.target.value },
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
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <label>작업명</label>
        <input type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <small className="hint">작업 큐와 보고서에서 구분할 이름입니다.</small>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <p className="section-title" style={{ marginTop: 0 }}>
          캠페인 설명
        </p>
        <div className="row cols-4">
          <div>
            <label>제품</label>
            <input type="text" value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} />
          </div>
          <div>
            <label>카테고리</label>
            <input
              type="text"
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            />
          </div>
          <div>
            <label>톤</label>
            <input type="text" value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })} />
          </div>
          <div>
            <label>목표</label>
            <input type="text" value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} />
          </div>
        </div>
        <label style={{ marginTop: 14 }}>추가 설명</label>
        <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <p className="section-title" style={{ marginTop: 0 }}>
          실행 옵션
        </p>
        <div className="row cols-5">
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
              <option value="ollama">ollama</option>
              <option value="mock">mock</option>
            </select>
          </div>
          <div>
            <label>Ollama 모델</label>
            <input
              type="text"
              value={form.ollama_model}
              onChange={(e) => setForm({ ...form, ollama_model: e.target.value })}
            />
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
        <label style={{ marginTop: 14 }}>버킷당 검색 수 (retrieval_k_per_bucket)</label>
        <input
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
            LLM 태스크 큐 사용 (페르소나별 LangChain/Ollama 호출 단위)
          </label>
        </div>
      </div>
    </form>
  );
}
