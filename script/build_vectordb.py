import argparse
import json
import time
import chromadb
import torch
from sentence_transformers import SentenceTransformer


def parse_args():
    parser = argparse.ArgumentParser(description="Nemotron Persona VectorDB 빌드 스크립트")
    parser.add_argument("--input-file", default="target_personas_20_59.jsonl")
    parser.add_argument("--db-path", default="./persona_db")
    parser.add_argument("--collection-name", default="marketing_personas")
    parser.add_argument("--model-name", default="jhgan/ko-sroberta-multitask")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--batch-size", type=int, default=4000)
    parser.add_argument("--encode-batch-size", type=int, default=512)
    parser.add_argument("--upsert-batch-size", type=int, default=5000)
    parser.add_argument("--max-records", type=int, default=0, help="0이면 전체 처리")
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
    t0 = time.perf_counter()

    # 1. 디스크 저장 모드 (RAM 사용량 최소화)
    client = chromadb.PersistentClient(path=args.db_path)

    # 2. 컬렉션 준비 (임베딩은 명시적으로 생성하여 전달)
    collection = client.get_or_create_collection(
        name=args.collection_name
    )
    model = SentenceTransformer(args.model_name, device=device)
    print(f"임베딩 모델 로드 완료: {args.model_name} (device={device})")

    batch_size = args.batch_size
    encode_batch_size = args.encode_batch_size
    upsert_batch_size = args.upsert_batch_size
    docs, metadatas, ids = [], [], []
    inserted = 0
    skipped = 0

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

    print("데이터 임베딩 및 DB 저장 시작...")
    with open(args.input_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            data = json.loads(line)

            # 안전장치: 벡터DB 적재 시점에서도 19~59세 범위만 허용(19세는 age_bucket=20s)
            age = to_int(data.get("age"), default=-1)
            if not (19 <= age <= 59):
                skipped += 1
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
                    "uuid": str(data.get("uuid", f"row_{i}")),
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
            ids.append(str(data.get("uuid", f"persona_{i}")))

            if len(docs) >= batch_size:
                flush_batch()
            if args.max_records > 0 and inserted + len(docs) >= args.max_records:
                break

        # 남은 데이터 처리
        flush_batch()

    elapsed = time.perf_counter() - t0
    throughput = inserted / elapsed if elapsed > 0 else 0.0
    print(
        f"Vector DB 구축 완료! (저장 위치: {args.db_path}, 컬렉션: {args.collection_name}, 적재: {inserted}건, "
        f"스킵: {skipped}건, 소요: {elapsed:.2f}초, 처리량: {throughput:.2f}건/초)"
    )

if __name__ == "__main__":
    main()