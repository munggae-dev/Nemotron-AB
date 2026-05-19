"""langchain-chroma로 기존 persona_db 컬렉션을 읽기 전용 래핑 (선택 경로)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from nemotron_ab.config import get_embed_model_name
from nemotron_ab.torch_device import resolve_chroma_lc_device
from nemotron_ab.persona_filter_schema import retrieval_fanout_multiplier
from nemotron_ab.persona_where import chroma_where_and, district_prefix_keyword


def get_chroma_vectorstore(
    db_path: Path | None = None,
    collection_name: str = "marketing_personas",
    model_name: str | None = None,
):
    """동일 임베딩으로 기존 Chroma 컬렉션을 LangChain VectorStore로 연다.

    `model_name` 미지정 시 `EMBED_MODEL_NAME` 환경변수 또는 기본값(BAAI/bge-m3)을 사용한다.
    """
    from langchain_chroma import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings

    path = db_path or (ROOT / "persona_db")
    device = resolve_chroma_lc_device()
    embeddings = HuggingFaceEmbeddings(
        model_name=get_embed_model_name(model_name),
        model_kwargs={"device": device},
    )
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=str(path),
    )


def similarity_search_with_age_filter(
    query: str,
    where: dict,
    k: int = 50,
    **kwargs: Any,
) -> list[Any]:
    """Chroma native `where`와 유사하게 메타 필터링된 검색 (LangChain 래퍼)."""
    vs = get_chroma_vectorstore(**kwargs)
    return vs.similarity_search(query, k=k, filter=where)


def retrieve_personas_langchain(
    payload: dict[str, Any],
    max_personas: int,
    k: int,
    **vs_kwargs: Any,
) -> list[dict[str, Any]]:
    """버킷별 검색+라운드로빈(기본). PERSONA_RETRIEVE_LEGACY=1이면 단일 쿼리."""
    from nemotron_ab.persona_retrieval import (
        build_retrieval_query_text,
        clamp_retrieval_k_per_bucket,
        retrieve_personas_balanced_langchain,
        use_legacy_single_query_retrieval,
    )

    if not use_legacy_single_query_retrieval():
        return retrieve_personas_balanced_langchain(
            payload,
            max_personas=max_personas,
            per_bucket_k=clamp_retrieval_k_per_bucket(k),
            **vs_kwargs,
        )

    query_text = build_retrieval_query_text(payload)
    persona_filter = payload["persona_filter"]
    occ_needle = str(persona_filter.get("occupation_contains", "") or "").strip()
    district_kw = district_prefix_keyword(persona_filter)
    where = chroma_where_and(persona_filter)
    base_n = max(int(k), int(max_personas), 20)
    mult = retrieval_fanout_multiplier(persona_filter)
    n_fetch = min(2000, max(base_n * mult, base_n))
    vs = get_chroma_vectorstore(**vs_kwargs)
    docs = vs.similarity_search(query_text, k=n_fetch, filter=where)
    rows: list[dict[str, Any]] = []
    for idx, doc in enumerate(docs):
        if len(rows) >= max_personas:
            break
        meta = dict(doc.metadata or {})
        row = {**meta}
        row["uuid"] = str(meta.get("uuid") or meta.get("id") or f"lc-{idx}")
        row["persona"] = doc.page_content or ""
        row.setdefault("age", 0)
        row.setdefault("sex", "미상")
        row.setdefault("occupation", "미상")
        row.setdefault("province", "미상")
        row.setdefault("district", "미상")
        if occ_needle and occ_needle not in str(row.get("occupation", "")):
            continue
        if district_kw and district_kw not in str(row.get("district", "")):
            continue
        rows.append(row)
    return rows
