import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

import chromadb
import torch
from sentence_transformers import SentenceTransformer


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "script" / "marketing_validator.py"
OUTPUT_BASE = ROOT_DIR / "outputs" / "jobs"
_RETRIEVAL_MODEL = None


def _make_campaign_payload(job_id: int, payload: Dict) -> List[Dict]:
    context = {
        "product": payload["product"],
        "category": payload["category"],
        "tone": payload["tone"],
        "goal": payload["goal"],
        "description": payload.get("description", ""),
    }
    return [
        {
            "id": f"job_{job_id}",
            "context": context,
            "copy_a": payload["copy_a"],
            "copy_b": payload["copy_b"],
        }
    ]


def _retrieve_filtered_personas(payload: Dict, max_personas: int) -> List[Dict]:
    db_path = str((ROOT_DIR / "persona_db").resolve())
    collection_name = "marketing_personas"
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_collection(name=collection_name)
    global _RETRIEVAL_MODEL
    if _RETRIEVAL_MODEL is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _RETRIEVAL_MODEL = SentenceTransformer("jhgan/ko-sroberta-multitask", device=device)

    persona_filter = payload["persona_filter"]
    where_conditions = [
        {"age": {"$gte": int(persona_filter["age_min"])}},
        {"age": {"$lte": int(persona_filter["age_max"])}},
    ]
    sex = persona_filter.get("sex", "all")
    if sex != "all":
        where_conditions.append({"sex": sex})
    province = persona_filter.get("province", "").strip()
    if province:
        where_conditions.append({"province": province})
    district = persona_filter.get("district", "").strip()
    if district:
        where_conditions.append({"district": district})
    where = {"$and": where_conditions}

    query_text = " ".join(
        [
            payload["product"],
            payload["category"],
            payload["tone"],
            payload["goal"],
            payload["copy_a"],
            payload["copy_b"],
            payload.get("description", ""),
        ]
    ).strip()
    n_results = max(max_personas * 3, 100)
    query_embedding = _RETRIEVAL_MODEL.encode(
        [query_text],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0].tolist()
    result = collection.query(
        query_embeddings=[query_embedding],
        where=where,
        n_results=n_results,
        include=["metadatas", "documents"],
    )
    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]

    rows: List[Dict] = []
    for idx, meta in enumerate(metas):
        row = dict(meta or {})
        row["uuid"] = ids[idx] if idx < len(ids) else f"p-{idx}"
        row["persona"] = docs[idx] if idx < len(docs) else ""
        # validator 정규화를 위한 최소 필드 보정
        row.setdefault("age", 0)
        row.setdefault("sex", "미상")
        row.setdefault("occupation", "미상")
        row.setdefault("province", "미상")
        row.setdefault("district", "미상")
        rows.append(row)
        if len(rows) >= max_personas:
            break
    return rows


def run_validator(job_id: int, payload: Dict) -> Tuple[Path, Path, Dict]:
    job_dir = OUTPUT_BASE / f"job_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    campaign_file = job_dir / "campaign.json"
    campaign_file.write_text(
        json.dumps(_make_campaign_payload(job_id, payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    max_personas = int(payload.get("max_personas") or 40)
    persona_rows = _retrieve_filtered_personas(payload, max_personas=max_personas)
    if not persona_rows:
        raise ValueError("필터 조건에 맞는 페르소나를 찾지 못했습니다.")
    persona_file = job_dir / "personas.jsonl"
    with persona_file.open("w", encoding="utf-8") as f:
        for row in persona_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    output_dir = job_dir / "result"
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(ROOT_DIR / "venv" / "bin" / "python"),
        str(SCRIPT_PATH),
        "--persona-source",
        "file",
        "--persona-file",
        str(persona_file),
        "--campaign-file",
        str(campaign_file),
        "--profile",
        payload["profile"],
        "--output-dir",
        str(output_dir),
        "--evaluator",
        payload["evaluator"],
        "--ollama-model",
        payload["ollama_model"],
        "--eval-concurrency",
        str(payload["eval_concurrency"]),
        "--max-personas",
        str(max_personas),
    ]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "validator 실행 실패")

    report_json = output_dir / f"job_{job_id}.report.json"
    partial_jsonl = output_dir / f"job_{job_id}.partial.jsonl"
    if not report_json.exists():
        candidates = sorted(output_dir.glob("*.report.json"))
        if not candidates:
            raise RuntimeError("리포트 파일이 생성되지 않았습니다.")
        report_json = candidates[0]
        partial_jsonl = output_dir / f"{report_json.stem.replace('.report', '')}.partial.jsonl"

    report_obj = json.loads(report_json.read_text(encoding="utf-8"))
    summary = {
        "final_winner": report_obj["report"]["final_winner"],
        "overall": report_obj["report"]["overall"],
        "key_reasons": report_obj["report"]["key_reasons"],
        "runtime": report_obj.get("runtime", {}),
    }
    return report_json, partial_jsonl, summary
