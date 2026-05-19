"""페르소나 검색용 임베딩 모델 A/B 벤치마크.

동일 페르소나 샘플·동일 임베딩 텍스트 스키마로 두 모델을 Chroma(메모리)에 적재한 뒤
검색 품질(메타데이터 정합, self-retrieval)과 인코딩 속도를 비교한다.

사용 예:
  ./venv/bin/python scripts/benchmark_embedding_models.py \\
    --sample-size 10000 \\
    --models BAAI/bge-m3 kekeappa/kor-static-embedding-512
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from nemotron_ab.torch_device import (  # noqa: E402
    DEVICE_CHOICES,
    prepare_sentence_transformer,
    resolve_torch_device,
)

# sanity_check_vectordb.py 와 동일한 페르소나 타깃 쿼리
PERSONA_QUERIES: list[tuple[str, dict[str, str]]] = [
    ("20대 여성 직장인, 패션과 SNS 관심 많음", {"age_bucket": "20s", "sex": "여자"}),
    ("50대 남성, 은퇴 준비와 재테크 관심", {"age_bucket": "50s", "sex": "남자"}),
    ("30대 워킹맘, 자녀 교육과 가족 여행", {"age_bucket": "30s", "sex": "여자"}),
    ("20대 대학생, 게임과 IT 트렌드 관심", {"age_bucket": "20s", "sex": "남자"}),
]

# A/B 캠페인 맥락형 쿼리 (validator_runner 검색 문구와 유사)
CAMPAIGN_QUERIES = [
    "20대 여성 대상 스킨케어 신제품 런칭. SNS 인플루언서 협업 카피 비교",
    "40대 직장인 남성 대상 보험 상품. 안정적 자산 형성 메시지",
    "30대 워킹맘 가족 여행 패키지. 주말 단기 여행 프로모션",
]


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_embedding_text(data: dict) -> str:
    core_parts = [
        f"나이: {to_int(data.get('age'))}세",
        f"성별: {data.get('sex', '미상')}",
        f"혼인: {data.get('marital_status', '')}",
        f"학력: {data.get('education_level', '')}",
        f"가구: {data.get('family_type', '')}",
        f"주택: {data.get('housing_type', '')}",
        f"병역: {data.get('military_status', '')}",
        f"직업: {data.get('occupation', '미상')}",
        f"거주: {data.get('province', '')} {data.get('district', '미상')}",
        f"대표 페르소나: {data.get('persona', '')}",
        f"직업 페르소나: {data.get('professional_persona', '')}",
        f"관심사: {data.get('hobbies_and_interests', '')}",
        f"커리어 목표: {data.get('career_goals_and_ambitions', '')}",
    ]
    return " | ".join(part for part in core_parts if part)


def age_bucket(age: int) -> str:
    if 19 <= age <= 29:
        return "20s"
    if 30 <= age <= 39:
        return "30s"
    if 40 <= age <= 49:
        return "40s"
    if 50 <= age <= 59:
        return "50s"
    return f"{(age // 10) * 10}s"


def load_personas(path: Path, sample_size: int, seed: int) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            age = to_int(data.get("age"), default=-1)
            if not (19 <= age <= 59):
                continue
            rows.append(data)
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:sample_size]


@dataclass
class ModelBenchResult:
    model: str
    dim: int
    index_rows_per_sec: float
    query_encode_ms: float
    metadata_hit_at_5: float
    metadata_hit_at_10: float
    self_retrieval_at_10: float
    avg_top1_distance: float


def bench_one_model(
    model_name: str,
    personas: list[dict],
    device: str,
    top_k: int,
    self_probe_n: int,
    seed: int,
    encode_batch_size: int,
) -> ModelBenchResult:
    docs: list[str] = []
    metas: list[dict] = []
    ids: list[str] = []
    for i, data in enumerate(personas):
        age = to_int(data.get("age"))
        pid = str(data.get("uuid", f"p-{i}"))
        docs.append(build_embedding_text(data))
        metas.append(
            {
                "uuid": pid,
                "age": age,
                "age_bucket": age_bucket(age),
                "sex": str(data.get("sex", "미상")),
                "occupation": str(data.get("occupation", "미상")),
            }
        )
        ids.append(pid)

    model = SentenceTransformer(model_name, device=device)
    prepare_sentence_transformer(model, device, "auto", 512)

    t0 = time.perf_counter()
    embeddings = model.encode(
        docs,
        batch_size=max(1, encode_batch_size),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    index_sec = time.perf_counter() - t0
    dim = int(embeddings.shape[1])

    client = chromadb.EphemeralClient()
    col = client.create_collection(name=f"bench_{uuid.uuid4().hex[:12]}")
    upsert_bs = 2000
    emb_list = embeddings.tolist()
    for start in range(0, len(docs), upsert_bs):
        end = start + upsert_bs
        col.upsert(
            ids=ids[start:end],
            documents=docs[start:end],
            metadatas=metas[start:end],
            embeddings=emb_list[start:end],
        )

    all_queries = [q for q, _ in PERSONA_QUERIES] + CAMPAIGN_QUERIES
    enc_times: list[float] = []
    top1_dists: list[float] = []
    hit5: list[float] = []
    hit10: list[float] = []

    for q, expected in PERSONA_QUERIES:
        tq = time.perf_counter()
        qe = model.encode(
            [q],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0].tolist()
        enc_times.append((time.perf_counter() - tq) * 1000.0)

        res = col.query(
            query_embeddings=[qe],
            n_results=top_k,
            include=["metadatas", "distances"],
        )
        mlist = res["metadatas"][0]
        dists = res["distances"][0]
        if dists:
            top1_dists.append(float(dists[0]))

        def match(meta: dict) -> bool:
            ok = True
            if "age_bucket" in expected:
                ok = ok and meta.get("age_bucket") == expected["age_bucket"]
            if "sex" in expected:
                ok = ok and meta.get("sex") == expected["sex"]
            return ok

        hit5.append(sum(1 for m in mlist[:5] if match(m)) / 5.0)
        hit10.append(sum(1 for m in mlist[:10] if match(m)) / 10.0)

    for q in CAMPAIGN_QUERIES:
        tq = time.perf_counter()
        qe = model.encode(
            [q],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0].tolist()
        enc_times.append((time.perf_counter() - tq) * 1000.0)
        res = col.query(
            query_embeddings=[qe],
            n_results=1,
            include=["distances"],
        )
        dists = res["distances"][0]
        if dists:
            top1_dists.append(float(dists[0]))

    rng = random.Random(seed)
    probe_idx = rng.sample(range(len(docs)), min(self_probe_n, len(docs)))
    self_hits = 0
    for idx in probe_idx:
        qe = embeddings[idx].tolist()
        res = col.query(query_embeddings=[qe], n_results=10)
        rank_ids = res["ids"][0]
        if ids[idx] in rank_ids:
            self_hits += 1
    self_rate = self_hits / len(probe_idx) if probe_idx else 0.0

    return ModelBenchResult(
        model=model_name,
        dim=dim,
        index_rows_per_sec=len(docs) / index_sec if index_sec > 0 else 0.0,
        query_encode_ms=float(np.mean(enc_times)) if enc_times else 0.0,
        metadata_hit_at_5=float(np.mean(hit5)) if hit5 else 0.0,
        metadata_hit_at_10=float(np.mean(hit10)) if hit10 else 0.0,
        self_retrieval_at_10=self_rate,
        avg_top1_distance=float(np.mean(top1_dists)) if top1_dists else 0.0,
    )


def parse_args():
    p = argparse.ArgumentParser(description="임베딩 모델 검색 품질·속도 벤치마크")
    p.add_argument("--input-file", default="target_personas_20_59.jsonl")
    p.add_argument("--sample-size", type=int, default=10000,
                   help="벤치마크에 쓸 페르소나 수. CPU·저사양은 500~2000 권장.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--self-probe-n", type=int, default=200,
                   help="self-retrieval 프로브 수. 0이면 sample_size의 10%%(최대 200).")
    p.add_argument("--encode-batch-size", type=int, default=256,
                   help="encode 배치. CPU·저메모리는 16~64 권장.")
    p.add_argument("--device", choices=list(DEVICE_CHOICES), default="auto")
    p.add_argument(
        "--models",
        nargs="+",
        default=["BAAI/bge-m3", "kekeappa/kor-static-embedding-512"],
    )
    p.add_argument("--output", default="outputs/benchmark_embeddings/summary.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    device = resolve_torch_device(args.device)
    input_path = Path(args.input_file)
    if not input_path.is_file():
        print(f"[ERROR] 입력 파일 없음: {input_path}")
        return 2

    personas = load_personas(input_path, args.sample_size, args.seed)
    if not personas:
        print("[ERROR] 페르소나 샘플이 비었습니다.")
        return 3

    self_probe_n = args.self_probe_n
    if self_probe_n <= 0:
        self_probe_n = min(200, max(20, len(personas) // 10))

    print(
        f"벤치마크 샘플: {len(personas):,}건, device={device}, "
        f"encode_batch={args.encode_batch_size}, self_probe={self_probe_n}"
    )
    results: list[ModelBenchResult] = []
    for name in args.models:
        print(f"\n=== {name} ===")
        try:
            r = bench_one_model(
                name,
                personas,
                device,
                args.top_k,
                self_probe_n,
                args.seed,
                args.encode_batch_size,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {name}: {exc}")
            continue
        results.append(r)
        print(f"  dim={r.dim}")
        print(f"  index={r.index_rows_per_sec:.0f} rows/s")
        print(f"  query_encode={r.query_encode_ms:.2f} ms")
        print(f"  metadata_hit@5={r.metadata_hit_at_5:.3f}  hit@10={r.metadata_hit_at_10:.3f}")
        print(f"  self_retrieval@10={r.self_retrieval_at_10:.3f}")
        print(f"  avg_top1_dist={r.avg_top1_distance:.4f} (L2, normalized)")

    if len(results) < 2:
        return 4 if not results else 0

    a, b = results[0], results[1]
    print("\n=== 비교 (첫 모델 vs 둘째 모델) ===")
    print(f"  {a.model}  vs  {b.model}")
    print(f"  metadata_hit@5:  {a.metadata_hit_at_5:.3f}  ->  {b.metadata_hit_at_5:.3f}  "
          f"({'kor-static 우세' if b.metadata_hit_at_5 > a.metadata_hit_at_5 else 'bge-m3 우세' if a.metadata_hit_at_5 > b.metadata_hit_at_5 else '동률'})")
    print(f"  self_retrieval@10: {a.self_retrieval_at_10:.3f} -> {b.self_retrieval_at_10:.3f}")
    print(f"  query_encode(ms): {a.query_encode_ms:.2f} -> {b.query_encode_ms:.2f}")
    print(f"  index(rows/s):    {a.index_rows_per_sec:.0f} -> {b.index_rows_per_sec:.0f}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sample_size": len(personas),
        "device": device,
        "models": [r.__dict__ for r in results],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
