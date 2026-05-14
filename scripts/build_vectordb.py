import argparse
import json
import os
import sys
import time
from pathlib import Path

# CUDA 메모리 단편화 완화: 반드시 torch import 전에 설정해야 효과 있음
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import chromadb
import torch
from sentence_transformers import SentenceTransformer

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from nemotron_ab.config import get_embed_model_name


def parse_args():
    parser = argparse.ArgumentParser(description="Nemotron Persona VectorDB 빌드 스크립트")
    parser.add_argument("--input-file", default="target_personas_20_59.jsonl")
    parser.add_argument("--db-path", default="./persona_db")
    parser.add_argument("--collection-name", default="marketing_personas")
    parser.add_argument(
        "--model-name",
        default=None,
        help="임베딩 모델. 미지정 시 env EMBED_MODEL_NAME 또는 기본값(BAAI/bge-m3) 사용.",
    )
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--batch-size", type=int, default=4000)
    parser.add_argument("--encode-batch-size", type=int, default=1024)
    parser.add_argument("--upsert-batch-size", type=int, default=5000)
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=512,
        help="임베딩 토크나이저 max_seq_length. bge-m3 기본 8192는 어텐션 비용 제곱으로 매우 비쌈. "
        "본 데이터(target_personas_20_59)는 실측 토큰 길이 max 507·p99 462 이라 512 면 잘림 없이 충분.",
    )
    parser.add_argument(
        "--fp16",
        choices=["auto", "on", "off"],
        default="auto",
        help="CUDA일 때 FP16 인코딩. TITAN RTX 등 Turing 이상에서 1.5~2배 속도. 기본 auto=CUDA면 on, CPU면 off.",
    )
    parser.add_argument("--max-records", type=int, default=0, help="0이면 전체 처리")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="기존 컬렉션의 ID 를 읽어와 이미 들어간 UUID 는 인코딩까지 건너뜁니다 (중단·재개용).",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=20000,
        help="진행률(%) 및 ETA 를 출력할 처리 건수 간격.",
    )
    return parser.parse_args()


def resolve_device(device_arg):
    if device_arg == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device_arg == "cuda" and not torch.cuda.is_available():
        print("[WARN] CUDA를 요청했지만 GPU를 찾지 못했습니다. CPU로 전환합니다.")
        return "cpu"
    return device_arg

def main():
    args = parse_args()
    device = resolve_device(args.device)
    model_name = get_embed_model_name(args.model_name)
    t0 = time.perf_counter()

    # 1. 디스크 저장 모드 (RAM 사용량 최소화)
    client = chromadb.PersistentClient(path=args.db_path)

    # 2. 컬렉션 준비 (임베딩은 명시적으로 생성하여 전달)
    collection = client.get_or_create_collection(
        name=args.collection_name
    )
    model = SentenceTransformer(model_name, device=device)
    if args.max_seq_length and args.max_seq_length > 0:
        model.max_seq_length = args.max_seq_length
    use_fp16 = (args.fp16 == "on") or (args.fp16 == "auto" and device == "cuda")
    if use_fp16:
        model.half()
    print(
        f"임베딩 모델 로드 완료: {model_name} "
        f"(device={device}, fp16={use_fp16}, max_seq_length={model.max_seq_length})"
    )

    batch_size = args.batch_size
    encode_batch_size = args.encode_batch_size
    upsert_batch_size = args.upsert_batch_size
    docs, metadatas, ids = [], [], []
    inserted = 0
    skipped = 0
    resumed_skipped = 0

    existing_ids: set = set()
    if args.resume:
        print("기존 컬렉션 ID 조회 중...")
        try:
            existing = collection.get(include=[])
            existing_ids = set(existing.get("ids", []) or [])
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 기존 ID 조회 실패 ({e}). 전체 재처리로 진행합니다.")
            existing_ids = set()
        print(f"이미 적재된 ID: {len(existing_ids):,}건 (인코딩 건너뜀)")

    def to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def build_embedding_text(data):
        # 실제 데이터 스키마(예: persona, professional_persona, hobbies...) 기반으로 고정 구성
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
    
    def flush_batch():
        nonlocal docs, metadatas, ids, inserted
        if not docs:
            return
        embeddings = model.encode(
            docs,
            batch_size=min(encode_batch_size, len(docs)),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        # Chroma 최대 배치 제한을 피하기 위해 upsert는 안전 크기로 분할
        emb_list = embeddings.tolist()
        for start in range(0, len(docs), upsert_batch_size):
            end = start + upsert_batch_size
            collection.upsert(
                documents=docs[start:end],
                metadatas=metadatas[start:end],
                ids=ids[start:end],
                embeddings=emb_list[start:end],
            )
        inserted += len(docs)
        print(f"{inserted}건 저장 완료...")
        docs, metadatas, ids = [], [], []
        if device == "cuda":
            # 활성화 메모리 단편화로 인한 OOM 방지
            torch.cuda.empty_cache()

    # 전체 입력 라인 수(진행률 표시용). 빠르게 한 번만 카운트.
    total_lines = 0
    try:
        with open(args.input_file, "r", encoding="utf-8") as _cf:
            for _ in _cf:
                total_lines += 1
    except OSError:
        total_lines = 0

    print(f"데이터 임베딩 및 DB 저장 시작... (입력 라인 {total_lines:,}건)")
    last_log_processed = 0
    loop_t0 = time.perf_counter()
    with open(args.input_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data = json.loads(line)

            # 안전장치: 벡터DB 적재 시점에서도 19~59세 범위만 허용(19세는 age_bucket=20s)
            age = to_int(data.get("age"), default=-1)
            if not (19 <= age <= 59):
                skipped += 1
                continue

            persona_id = str(data.get("uuid", f"persona_{i}"))
            if existing_ids and persona_id in existing_ids:
                resumed_skipped += 1
                processed = inserted + len(docs) + resumed_skipped
                if total_lines and processed - last_log_processed >= args.progress_every:
                    pct = processed * 100.0 / total_lines
                    elapsed = time.perf_counter() - loop_t0
                    rate = processed / elapsed if elapsed > 0 else 0.0
                    remaining = max(0, total_lines - processed)
                    eta_sec = remaining / rate if rate > 0 else 0
                    print(
                        f"진행 {processed:,}/{total_lines:,} ({pct:.1f}%) "
                        f"resume-skip={resumed_skipped:,} "
                        f"속도={rate:.0f} rows/s ETA={eta_sec/60:.1f}min",
                        flush=True,
                    )
                    last_log_processed = processed
                continue

            # 검색 정확도를 높이기 위해 의미있는 필드로 임베딩 텍스트 구성
            text_to_embed = build_embedding_text(data)

            docs.append(text_to_embed)
            # 메타데이터 확장: 연령대/성별/직업/지역 필터를 빠르게 수행 가능
            if 19 <= age <= 29:
                age_bucket = "20s"
            elif 30 <= age <= 39:
                age_bucket = "30s"
            elif 40 <= age <= 49:
                age_bucket = "40s"
            elif 50 <= age <= 59:
                age_bucket = "50s"
            else:
                age_bucket = f"{(age // 10) * 10}s"

            metadatas.append(
                {
                    "uuid": persona_id,
                    "age": age,
                    "age_bucket": age_bucket,
                    "sex": str(data.get("sex", "미상")),
                    "occupation": str(data.get("occupation", "미상")),
                    "province": str(data.get("province", "미상")),
                    "district": str(data.get("district", "미상")),
                    "marital_status": str(data.get("marital_status", "")),
                    "education_level": str(data.get("education_level", "")),
                    "family_type": str(data.get("family_type", "")),
                    "housing_type": str(data.get("housing_type", "")),
                    "military_status": str(data.get("military_status", "")),
                }
            )
            # 재빌드 안정성을 위해 인덱스 대신 데이터 고유값(uuid) 사용
            ids.append(persona_id)

            if len(docs) >= batch_size:
                flush_batch()
                processed = inserted + resumed_skipped
                if total_lines and processed - last_log_processed >= args.progress_every:
                    pct = processed * 100.0 / total_lines
                    elapsed = time.perf_counter() - loop_t0
                    rate = processed / elapsed if elapsed > 0 else 0.0
                    remaining = max(0, total_lines - processed)
                    eta_sec = remaining / rate if rate > 0 else 0
                    print(
                        f"진행 {processed:,}/{total_lines:,} ({pct:.1f}%) "
                        f"신규={inserted:,} resume-skip={resumed_skipped:,} "
                        f"속도={rate:.0f} rows/s ETA={eta_sec/60:.1f}min",
                        flush=True,
                    )
                    last_log_processed = processed
            if args.max_records > 0 and inserted + len(docs) >= args.max_records:
                break

        # 남은 데이터 처리
        flush_batch()

    elapsed = time.perf_counter() - t0
    throughput = inserted / elapsed if elapsed > 0 else 0.0
    print(
        f"Vector DB 구축 완료! (저장 위치: {args.db_path}, 컬렉션: {args.collection_name}, "
        f"신규 적재: {inserted}건, resume-skip: {resumed_skipped}건, age-skip: {skipped}건, "
        f"소요: {elapsed:.2f}초, 신규 처리량: {throughput:.2f}건/초)"
    )

if __name__ == "__main__":
    main()