"""persona_db 기반 모수(표본 수) 추정."""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import chromadb

from backend.deps import REPO_ROOT
from nemotron_ab.persona_where import chroma_where_and, district_prefix_keyword


def estimate_population_size(persona_filter: Mapping[str, Any]) -> dict[str, Any]:
    """현재 persona_db에서 필터 조건에 맞는 표본 수를 빠르게 추정.

    전체 스캔이 길어지는 환경을 피하기 위해 스캔 건수/시간 상한을 둔다.
    """
    db_path = str((REPO_ROOT / "persona_db").resolve())
    collection_name = "marketing_personas"
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_collection(name=collection_name)

    where = chroma_where_and(dict(persona_filter))
    occ_needle = str(persona_filter.get("occupation_contains", "") or "").strip()
    district_kw = district_prefix_keyword(dict(persona_filter))
    page_size = 500
    max_scan_rows = 10000
    max_elapsed_sec = 3.0
    started = time.perf_counter()
    offset = 0
    total = 0
    scanned = 0
    capped = False
    while True:
        include_fields = ["metadatas"] if (occ_needle or district_kw) else []
        result = collection.get(where=where, include=include_fields, limit=page_size, offset=offset)
        metas = result.get("metadatas") or []
        ids = result.get("ids") or []
        if not metas:
            if not ids:
                break
        scanned += len(metas) if metas else len(ids)
        if occ_needle or district_kw:
            matched = 0
            for m in metas:
                mm = m or {}
                if occ_needle and occ_needle not in str(mm.get("occupation", "")):
                    continue
                if district_kw and district_kw not in str(mm.get("district", "")):
                    continue
                matched += 1
            total += matched
        else:
            total += len(ids)
        page_len = len(metas) if metas else len(ids)
        if page_len < page_size:
            break
        if scanned >= max_scan_rows or (time.perf_counter() - started) >= max_elapsed_sec:
            capped = True
            break
        offset += page_len
    return {"count": int(total), "capped": capped, "scanned": scanned}
