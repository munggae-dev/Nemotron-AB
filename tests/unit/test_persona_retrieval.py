"""persona_retrieval: 버킷 경계·라운드로빈·where 조건."""
from __future__ import annotations

import pytest

from nemotron_ab.persona_retrieval import (
    active_age_bucket_count,
    bucket_query_age_bounds,
    chroma_where_for_bucket,
    merge_rows_round_robin,
    retrieval_pool_capacity,
)


def test_bucket_query_age_bounds_respects_filter():
    pf = {"age_min": 35, "age_max": 55}
    assert bucket_query_age_bounds("20s", pf) is None
    assert bucket_query_age_bounds("30s", pf) == (35, 39)
    assert bucket_query_age_bounds("40s", pf) == (40, 49)
    assert bucket_query_age_bounds("50s", pf) == (50, 55)


def test_active_age_bucket_count_full_range():
    pf = {"age_min": 19, "age_max": 59}
    assert active_age_bucket_count(pf) == 4
    assert retrieval_pool_capacity(pf, 20) == 80


def test_chroma_where_for_bucket_includes_sex():
    pf = {"age_min": 19, "age_max": 59, "sex": "female"}
    where = chroma_where_for_bucket(pf, "30s")
    assert where is not None
    assert {"age": {"$gte": 30}} in where["$and"]
    assert {"age": {"$lte": 39}} in where["$and"]
    assert {"sex": "female"} in where["$and"]


def test_merge_rows_round_robin_interleaves_buckets():
    per_bucket = {
        "20s": [{"uuid": "a1"}, {"uuid": "a2"}],
        "30s": [{"uuid": "b1"}],
        "40s": [{"uuid": "c1"}, {"uuid": "c2"}],
        "50s": [],
    }
    merged = merge_rows_round_robin(per_bucket, max_personas=4)
    assert [r["uuid"] for r in merged] == ["a1", "b1", "c1", "a2"]


def test_merge_rows_round_robin_stops_at_max():
    per_bucket = {b: [{"uuid": f"{b}-{i}"} for i in range(5)] for b in ("20s", "30s", "40s", "50s")}
    merged = merge_rows_round_robin(per_bucket, max_personas=6)
    assert len(merged) == 6
