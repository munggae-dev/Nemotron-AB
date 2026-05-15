"""Nemotron Persona VectorDB sanity check.

빌드한 `persona_db` 컬렉션이 정상 동작하는지 빠르게 확인한다.

  - 총 적재 건수
  - 메타데이터 분포 (age_bucket, sex, age 범위)
  - 임베딩 차원
  - where 필터 동작 (age_bucket + sex)
  - 의미 기반 top-k 쿼리 (기본 한국어 4문장)

사용 예:
  ./venv/bin/python scripts/sanity_check_vectordb.py
  ./venv/bin/python scripts/sanity_check_vectordb.py --top-k 3 \
      --queries "20대 여성 직장인 패션 관심" "50대 남성 은퇴 재테크"
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from nemotron_ab.config import get_embed_model_name
from nemotron_ab.torch_device import (
    DEVICE_CHOICES,
    prepare_sentence_transformer,
    resolve_torch_device,
)

DEFAULT_QUERIES = [
    "20대 여성 직장인, 패션과 SNS 관심 많음",
    "50대 남성, 은퇴 준비와 재테크 관심",
    "30대 워킹맘, 자녀 교육과 가족 여행",
    "20대 대학생, 게임과 IT 트렌드 관심",
]


def parse_args():
    p = argparse.ArgumentParser(description="Persona VectorDB sanity check")
    p.add_argument("--db-path", default="./persona_db")
    p.add_argument("--collection-name", default="marketing_personas")
    p.add_argument("--model-name", default=None,
                   help="임베딩 모델. 미지정 시 env EMBED_MODEL_NAME 또는 기본값.")
    p.add_argument("--device", choices=list(DEVICE_CHOICES), default="auto")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument(
        "--queries",
        nargs="*",
        default=DEFAULT_QUERIES,
        help="의미 기반 검색에 사용할 쿼리 목록. 빈 값으로 주면 검색 스킵.",
    )
    p.add_argument("--sample-size", type=int, default=20000,
                   help="분포 확인용 누적 표본 수 (5천 페이지 단위로 가져옴).")
    p.add_argument("--filter-age-bucket", default="30s")
    p.add_argument("--filter-sex", default="여자")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    device = resolve_torch_device(args.device)

    t0 = time.perf_counter()
    client = chromadb.PersistentClient(path=args.db_path)
    try:
        col = client.get_collection(args.collection_name)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 컬렉션을 열 수 없습니다: {exc}")
        return 2

    print("=== 1) Collection 카운트 ===")
    total = col.count()
    print(f"총 적재 건수: {total:,}")
    if total == 0:
        print("[ERROR] 컬렉션이 비어있습니다. 빌드를 먼저 수행하세요.")
        return 3

    print("\n=== 2) 메타데이터 분포 (페이지 5천씩 누적 샘플) ===")
    metas: list = []
    page = 5000
    off = 0
    target = max(0, args.sample_size)
    while target > 0 and len(metas) < target:
        g = col.get(limit=page, offset=off, include=["metadatas"])
        ms = g.get("metadatas") or []
        if not ms:
            break
        metas.extend(ms)
        off += page
    print(f"표본 {len(metas):,}건")
    age_int = [m.get("age") for m in metas if isinstance(m.get("age"), int)]
    print(f"  age_bucket: {dict(Counter(m.get('age_bucket') for m in metas))}")
    print(f"  sex       : {dict(Counter(m.get('sex') for m in metas))}")
    if age_int:
        print(f"  age 범위   : min={min(age_int)} max={max(age_int)} "
              f"mean={sum(age_int)/len(age_int):.1f}")

    print("\n=== 3) 임베딩 차원 ===")
    e = col.get(limit=1, include=["embeddings"])
    embs = e.get("embeddings")
    if not embs:
        print("[WARN] 임베딩을 가져오지 못했습니다.")
    else:
        dim = len(embs[0])
        print(f"  dim = {dim}")

    print(f"\n=== 4) where 필터 sanity "
          f"(age_bucket={args.filter_age_bucket} AND sex={args.filter_sex}) ===")
    filt = {"$and": [
        {"age_bucket": {"$eq": args.filter_age_bucket}},
        {"sex": {"$eq": args.filter_sex}},
    ]}
    sub = col.get(where=filt, limit=200, include=["metadatas"])
    sm = sub.get("metadatas") or []
    print(f"  매칭 상위 200건: {len(sm)}건")
    if sm:
        print(f"  age_bucket: {dict(Counter(m.get('age_bucket') for m in sm))}")
        print(f"  sex       : {dict(Counter(m.get('sex') for m in sm))}")

    queries = [q for q in (args.queries or []) if q]
    if queries:
        print(f"\n=== 5) 의미 기반 top-{args.top_k} 쿼리 ===")
        model = SentenceTransformer(
            get_embed_model_name(args.model_name), device=device,
        )
        prepare_sentence_transformer(model, device, "auto", 512)
        for q in queries:
            qe = model.encode(
                [q],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0].tolist()
            res = col.query(
                query_embeddings=[qe],
                n_results=args.top_k,
                include=["metadatas", "documents", "distances"],
            )
            print(f"\n[Q] {q}")
            metas_q = res["metadatas"][0]
            docs_q = res["documents"][0]
            dists_q = res["distances"][0]
            for i, (m, d, dist) in enumerate(zip(metas_q, docs_q, dists_q, strict=False)):
                print(
                    f"  {i+1}. dist={dist:.4f} age={m.get('age')} sex={m.get('sex')} "
                    f"occ={m.get('occupation')} {m.get('province')}/{m.get('district')}"
                )
                print(f"     {(d or '')[:140]}...")

    print(f"\n총 소요: {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
