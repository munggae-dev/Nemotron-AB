"""persona_db 배포용 manifest.json 생성기.

오픈소스로 미리 빌드된 VectorDB를 배포할 때, 같이 동봉하면 좋은 메타정보를
JSON으로 떨어뜨린다. 사용자는 이 파일만 보고 차원·임베딩 모델·텍스트 스키마·해시를
검증할 수 있다.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import chromadb

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from nemotron_ab.config import get_embed_model_name

# build_vectordb.py 와 동일하게 유지해야 한다. 변경 시 schema_version 도 같이 올린다.
EMBEDDING_TEXT_FIELDS_ORDER = [
    "age",
    "sex",
    "marital_status",
    "education_level",
    "family_type",
    "housing_type",
    "military_status",
    "occupation",
    "province",
    "district",
    "persona",
    "professional_persona",
    "hobbies_and_interests",
    "career_goals_and_ambitions",
]
EMBEDDING_TEXT_SCHEMA_VERSION = "v1"


def sha256_file(path: Path, chunk: int = 64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def parse_args():
    p = argparse.ArgumentParser(description="persona_db manifest.json 생성")
    p.add_argument("--db-path", default="./persona_db")
    p.add_argument("--collection-name", default="marketing_personas")
    p.add_argument("--embedding-model", default=None,
                   help="미지정 시 nemotron_ab.config 기본값(BAAI/bge-m3)")
    p.add_argument("--embedding-dim", type=int, default=1024)
    p.add_argument("--max-seq-length", type=int, default=512)
    p.add_argument("--fp16", choices=["true", "false"], default="true")
    p.add_argument("--source-dataset", default="nvidia/Nemotron-Personas-Korea")
    p.add_argument("--source-license", default="CC-BY-4.0")
    p.add_argument("--age-filter", default="19~59")
    p.add_argument("--chroma-distance", default="l2",
                   help="컬렉션 생성 시 hnsw:space (Chroma 기본 l2)")
    p.add_argument("--out", default=None,
                   help="저장 경로. 미지정 시 <db-path>/manifest.json")
    p.add_argument("--skip-hash", action="store_true",
                   help="SHA-256 계산 생략 (대용량 시 빠름)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path).resolve()
    if not db_path.exists():
        print(f"[ERROR] DB 경로가 없습니다: {db_path}")
        return 2

    client = chromadb.PersistentClient(path=str(db_path))
    try:
        col = client.get_collection(args.collection_name)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 컬렉션 열기 실패: {exc}")
        return 3

    row_count = col.count()
    col_metadata = dict(col.metadata or {})

    print(f"DB: {db_path}")
    print(f"컬렉션: {args.collection_name}  row_count={row_count:,}")

    files: dict = {}
    sha: dict = {}
    for root, _, fnames in os.walk(db_path):
        for fn in fnames:
            if fn == "manifest.json":
                continue
            fp = Path(root) / fn
            rel = str(fp.relative_to(db_path))
            files[rel] = fp.stat().st_size

    if not args.skip_hash:
        for rel, size in files.items():
            fp = db_path / rel
            t0 = time.perf_counter()
            sha[rel] = sha256_file(fp)
            gb = size / 1e9
            sec = time.perf_counter() - t0
            print(f"  sha256({rel}) = {sha[rel][:16]}…  ({sec:.1f}s, {gb:.2f}GB)")

    manifest = {
        "schema_version": EMBEDDING_TEXT_SCHEMA_VERSION,
        "built_at": time.strftime("%Y-%m-%d"),
        "source": {
            "dataset": args.source_dataset,
            "license": args.source_license,
            "age_filter": args.age_filter,
        },
        "embedding": {
            "model": get_embed_model_name(args.embedding_model),
            "dim": args.embedding_dim,
            "normalize": True,
            "max_seq_length": args.max_seq_length,
            "fp16_inference": args.fp16 == "true",
            "text_fields_order": EMBEDDING_TEXT_FIELDS_ORDER,
            "text_schema_version": EMBEDDING_TEXT_SCHEMA_VERSION,
        },
        "chroma": {
            "collection_name": args.collection_name,
            "distance": args.chroma_distance,
            "collection_metadata": col_metadata,
        },
        "row_count": row_count,
        "files": files,
        "sha256": sha,
        "license_note": (
            "임베딩과 메타데이터는 원본 데이터셋(Nemotron-Personas-Korea, CC-BY-4.0)의 "
            "파생물이며 동일 라이선스를 따른다. 사용 시 NVIDIA 데이터셋 출처를 표기할 것."
        ),
    }

    out = Path(args.out) if args.out else db_path / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n매니페스트 저장: {out}  (files={len(files)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
