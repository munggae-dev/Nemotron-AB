"""페르소나 벡터 검색: 연령 버킷별 후보 수집 + 라운드로빈 병합."""
from __future__ import annotations

import os
import random
from typing import Any

from nemotron_ab.campaign_assets import payload_has_any_image
from nemotron_ab.persona_filter_schema import retrieval_fanout_multiplier
from nemotron_ab.persona_where import (
    _NEMOTRON_META_KEYS,
    district_exact_token,
    district_prefix_keyword,
    normalize_province,
)

AGE_BUCKETS = ("20s", "30s", "40s", "50s")


def age_to_bucket(age: int) -> str | None:
    if 19 <= age <= 29:
        return "20s"
    if 30 <= age <= 39:
        return "30s"
    if 40 <= age <= 49:
        return "40s"
    if 50 <= age <= 59:
        return "50s"
    return None


def bucket_age_bounds(bucket: str) -> tuple[int, int]:
    if bucket == "20s":
        return 19, 29
    if bucket == "30s":
        return 30, 39
    if bucket == "40s":
        return 40, 49
    if bucket == "50s":
        return 50, 59
    raise ValueError(f"unknown bucket: {bucket}")


def bucket_query_age_bounds(bucket: str, persona_filter: dict[str, Any]) -> tuple[int, int] | None:
    """필터 나이 범위와 버킷 구간의 교집합. 없으면 None."""
    lo_b, hi_b = bucket_age_bounds(bucket)
    age_min = int(persona_filter.get("age_min", 19))
    age_max = int(persona_filter.get("age_max", 59))
    lo = max(lo_b, age_min)
    hi = min(hi_b, age_max)
    if lo > hi:
        return None
    return lo, hi


def active_age_bucket_count(persona_filter: dict[str, Any]) -> int:
    return sum(1 for b in AGE_BUCKETS if bucket_query_age_bounds(b, persona_filter) is not None)


def chroma_where_for_bucket(persona_filter: dict[str, Any], bucket: str) -> dict[str, Any] | None:
    """버킷별 Chroma where (연령은 버킷 구간으로 한정)."""
    bounds = bucket_query_age_bounds(bucket, persona_filter)
    if bounds is None:
        return None
    lo, hi = bounds
    clauses: list[dict[str, Any]] = [
        {"age": {"$gte": lo}},
        {"age": {"$lte": hi}},
    ]
    sex = persona_filter.get("sex", "all")
    if sex != "all":
        clauses.append({"sex": sex})
    province = normalize_province(str(persona_filter.get("province", "") or ""))
    if province:
        clauses.append({"province": province})
    district = district_exact_token(persona_filter)
    if district:
        clauses.append({"district": district})
    for key in _NEMOTRON_META_KEYS:
        val = str(persona_filter.get(key, "") or "").strip()
        if val:
            clauses.append({key: val})
    return {"$and": clauses}


def build_retrieval_query_text(payload: dict[str, Any]) -> str:
    query_text = " ".join(
        [
            str(payload.get("context", "") or ""),
            str(payload.get("text_a", "") or ""),
            str(payload.get("text_b", "") or ""),
        ]
    ).strip()
    if payload_has_any_image(payload):
        suffix = "이미지 크리에이티브 포함"
        return f"{query_text} {suffix}".strip() if query_text else suffix
    return query_text


def clamp_retrieval_k_per_bucket(raw: Any) -> int:
    return max(20, min(500, int(raw or 80)))


def retrieval_pool_capacity(persona_filter: dict[str, Any], per_bucket_k: int) -> int:
    """버킷별 k × 활성 버킷 수 (상한)."""
    return active_age_bucket_count(persona_filter) * clamp_retrieval_k_per_bucket(per_bucket_k)


def use_legacy_single_query_retrieval() -> bool:
    return os.environ.get("PERSONA_RETRIEVE_LEGACY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _row_passes_post_filters(row: dict[str, Any], occ_needle: str, district_kw: str) -> bool:
    if occ_needle and occ_needle not in str(row.get("occupation", "")):
        return False
    if district_kw and district_kw not in str(row.get("district", "")):
        return False
    return True


def _normalize_row(meta: dict[str, Any], doc: str, uid: str) -> dict[str, Any]:
    row = dict(meta or {})
    row["uuid"] = uid
    row["persona"] = doc
    row.setdefault("age", 0)
    row.setdefault("sex", "미상")
    row.setdefault("occupation", "미상")
    row.setdefault("province", "미상")
    row.setdefault("district", "미상")
    return row


def merge_rows_round_robin(
    per_bucket: dict[str, list[dict[str, Any]]],
    max_personas: int,
) -> list[dict[str, Any]]:
    """연령 버킷 균등 우선: 각 라운드에서 20s→30s→40s→50s 순으로 1명씩."""
    merged: list[dict[str, Any]] = []
    round_idx = 0
    while len(merged) < max_personas:
        progressed = False
        for bucket in AGE_BUCKETS:
            lst = per_bucket.get(bucket) or []
            if round_idx < len(lst) and len(merged) < max_personas:
                merged.append(lst[round_idx])
                progressed = True
        if not progressed:
            break
        round_idx += 1
    return merged[:max_personas]


def retrieve_personas_balanced_chroma(
    collection: Any,
    query_embedding: list[float],
    payload: dict[str, Any],
    *,
    max_personas: int,
    per_bucket_k: int | None = None,
) -> list[dict[str, Any]]:
    """버킷별 의미 검색 후 라운드로빈으로 max_personas 명까지 선택."""
    persona_filter = payload["persona_filter"]
    rk = clamp_retrieval_k_per_bucket(per_bucket_k if per_bucket_k is not None else payload.get("retrieval_k_per_bucket"))
    occ_needle = str(persona_filter.get("occupation_contains", "") or "").strip()
    district_kw = district_prefix_keyword(persona_filter)
    seed = int(payload.get("seed", 42))
    rng = random.Random(seed)

    per_bucket: dict[str, list[dict[str, Any]]] = {b: [] for b in AGE_BUCKETS}
    for bucket in AGE_BUCKETS:
        where = chroma_where_for_bucket(persona_filter, bucket)
        if where is None:
            continue
        result = collection.query(
            query_embeddings=[query_embedding],
            where=where,
            n_results=rk,
            include=["metadatas", "documents"],
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        bucket_rows: list[dict[str, Any]] = []
        for idx, meta in enumerate(metas):
            row = _normalize_row(
                meta if isinstance(meta, dict) else {},
                docs[idx] if idx < len(docs) else "",
                ids[idx] if idx < len(ids) else f"{bucket}-{idx}",
            )
            if not _row_passes_post_filters(row, occ_needle, district_kw):
                continue
            bucket_rows.append(row)
        rng.shuffle(bucket_rows)
        per_bucket[bucket] = bucket_rows

    merged = merge_rows_round_robin(per_bucket, max_personas)
    if merged or not district_kw:
        return merged

    # district 부분일치: 기존과 같이 필터 스캔 폴백
    from nemotron_ab.persona_where import chroma_where_and

    where = chroma_where_and(persona_filter)
    mult = retrieval_fanout_multiplier(persona_filter)
    n_results = min(2000, max(max_personas * mult, max_personas, 20))
    offset = 0
    page = 1000
    fallback: list[dict[str, Any]] = []
    while len(fallback) < max_personas:
        got = collection.get(where=where, limit=page, offset=offset, include=["metadatas", "documents"])
        g_ids = got.get("ids") or []
        g_docs = got.get("documents") or []
        g_metas = got.get("metadatas") or []
        if not g_metas:
            break
        for idx, meta in enumerate(g_metas):
            if len(fallback) >= max_personas:
                break
            row = _normalize_row(
                meta if isinstance(meta, dict) else {},
                g_docs[idx] if idx < len(g_docs) else "",
                g_ids[idx] if idx < len(g_ids) else f"fallback-{offset + idx}",
            )
            if not _row_passes_post_filters(row, occ_needle, district_kw):
                continue
            fallback.append(row)
        if len(g_metas) < page:
            break
        offset += len(g_metas)
    return fallback[:max_personas]


def retrieve_personas_balanced_langchain(
    payload: dict[str, Any],
    *,
    max_personas: int,
    per_bucket_k: int | None = None,
    **vs_kwargs: Any,
) -> list[dict[str, Any]]:
    from nemotron_ab.chroma_langchain import get_chroma_vectorstore

    persona_filter = payload["persona_filter"]
    rk = clamp_retrieval_k_per_bucket(per_bucket_k if per_bucket_k is not None else payload.get("retrieval_k_per_bucket"))
    query_text = build_retrieval_query_text(payload)
    occ_needle = str(persona_filter.get("occupation_contains", "") or "").strip()
    district_kw = district_prefix_keyword(persona_filter)
    seed = int(payload.get("seed", 42))
    rng = random.Random(seed)
    vs = get_chroma_vectorstore(**vs_kwargs)

    per_bucket: dict[str, list[dict[str, Any]]] = {b: [] for b in AGE_BUCKETS}
    for bucket in AGE_BUCKETS:
        where = chroma_where_for_bucket(persona_filter, bucket)
        if where is None:
            continue
        docs = vs.similarity_search(query_text, k=rk, filter=where)
        bucket_rows: list[dict[str, Any]] = []
        for idx, doc in enumerate(docs):
            meta = dict(doc.metadata or {})
            row = _normalize_row(
                meta,
                doc.page_content or "",
                str(meta.get("uuid") or meta.get("id") or f"lc-{bucket}-{idx}"),
            )
            if not _row_passes_post_filters(row, occ_needle, district_kw):
                continue
            bucket_rows.append(row)
        rng.shuffle(bucket_rows)
        per_bucket[bucket] = bucket_rows

    return merge_rows_round_robin(per_bucket, max_personas)
