"""langchain-chroma로 기존 persona_db 컬렉션을 읽기 전용 래핑 (선택 경로)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

from app.campaign_assets import payload_has_any_image
from app.persona_filter_schema import retrieval_fanout_multiplier
from app.persona_where import chroma_where_and


def get_chroma_vectorstore(
    db_path: Optional[Path] = None,
    collection_name: str = "marketing_personas",
    model_name: str = "jhgan/ko-sroberta-multitask",
):
    """동일 임베딩으로 기존 Chroma 컬렉션을 LangChain VectorStore로 연다."""
    from langchain_chroma import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings

    path = db_path or (ROOT / "persona_db")
    device = "cuda" if os.environ.get("CHROMA_LC_DEVICE", "").lower() == "cuda" else "cpu"
    embeddings = HuggingFaceEmbeddings(model_name=model_name, model_kwargs={"device": device})
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
) -> List[Any]:
    """Chroma native `where`와 유사하게 메타 필터링된 검색 (LangChain 래퍼)."""
    vs = get_chroma_vectorstore(**kwargs)
    return vs.similarity_search(query, k=k, filter=where)


def retrieve_personas_langchain(
    payload: Dict[str, Any],
    max_personas: int,
    k: int,
    **vs_kwargs: Any,
) -> List[Dict[str, Any]]:
    """validator_runner와 동일한 쿼리·필터로 LangChain Chroma 검색 후 행 dict 목록."""
    query_text = " ".join(
        [
            str(payload.get("product", "")),
            str(payload.get("category", "")),
            str(payload.get("tone", "")),
            str(payload.get("goal", "")),
            str(payload.get("copy_a", "")),
            str(payload.get("copy_b", "")),
            str(payload.get("description", "")),
        ]
    ).strip()
    if payload_has_any_image(payload):
        query_text = f"{query_text} 이미지 크리에이티브 포함".strip()
    persona_filter = payload["persona_filter"]
    occ_needle = str(persona_filter.get("occupation_contains", "") or "").strip()
    where = chroma_where_and(persona_filter)
    base_n = max(int(k), int(max_personas), 20)
    mult = retrieval_fanout_multiplier(persona_filter)
    n_fetch = min(2000, max(base_n * mult, base_n))
    vs = get_chroma_vectorstore(**vs_kwargs)
    docs = vs.similarity_search(query_text, k=n_fetch, filter=where)
    rows: List[Dict[str, Any]] = []
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
        rows.append(row)
    return rows
