import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]

# 서브프로세스: unset 또는 0 이하 → 타임아웃 없음(기존과 동일). 예: 3600
_ENV_SUBPROCESS_TIMEOUT = "AB_VALIDATOR_SUBPROCESS_TIMEOUT_SEC"
# 1/true/yes → stdout/stderr를 캡처하지 않고 상속(디버깅용)
_ENV_SUBPROCESS_STREAM = "MARKETING_VALIDATOR_SUBPROCESS_STREAM"
_MAX_ERR_CHARS = 6000


def _truncate_for_error(text: str, limit: int = _MAX_ERR_CHARS) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [출력 잘림] ..."


def _subprocess_timeout_sec() -> Optional[float]:
    raw = os.environ.get(_ENV_SUBPROCESS_TIMEOUT, "").strip()
    if not raw:
        return None
    try:
        sec = float(raw)
    except ValueError:
        return None
    return sec if sec > 0 else None


def _subprocess_stream_output() -> bool:
    return os.environ.get(_ENV_SUBPROCESS_STREAM, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _cmd_summary(cmd: List[str]) -> str:
    if not cmd:
        return "(빈 명령)"
    if len(cmd) <= 2:
        return " ".join(cmd)
    return f"{cmd[0]} {cmd[1]} ... ({len(cmd)} 인자)"


def _format_subprocess_failure(completed: subprocess.CompletedProcess, cmd: List[str]) -> str:
    parts = [
        f"validator 종료 코드 {completed.returncode}",
        f"명령: {_cmd_summary(cmd)}",
    ]
    err = _truncate_for_error(completed.stderr or "")
    out = _truncate_for_error(completed.stdout or "")
    if err:
        parts.append(f"stderr:\n{err}")
    if out:
        parts.append(f"stdout:\n{out}")
    if not err and not out:
        parts.append("(캡처된 stdout/stderr 없음)")
    return "\n\n".join(parts)


def _format_timeout_error(cmd: List[str], timeout_sec: Optional[float], exc: subprocess.TimeoutExpired) -> str:
    ts_display = str(timeout_sec) if timeout_sec is not None else "?"
    parts = [
        f"validator 서브프로세스 타임아웃 ({ts_display}초, {_ENV_SUBPROCESS_TIMEOUT})",
        f"명령: {_cmd_summary(cmd)}",
    ]

    def _maybe_text(chunk: object) -> str:
        if chunk is None:
            return ""
        if isinstance(chunk, bytes):
            return chunk.decode(errors="replace")
        return str(chunk)

    out = _maybe_text(exc.output)
    err = _maybe_text(exc.stderr)
    if out:
        parts.append(f"stdout(일부):\n{_truncate_for_error(out)}")
    if err:
        parts.append(f"stderr(일부):\n{_truncate_for_error(err)}")
    return "\n\n".join(parts)


def _run_ab_validator_subprocess(cmd: List[str]) -> subprocess.CompletedProcess:
    timeout = _subprocess_timeout_sec()
    stream = _subprocess_stream_output()
    base_kw: Dict[str, Any] = {
        "check": False,
        "cwd": str(ROOT_DIR),
    }
    if timeout is not None:
        base_kw["timeout"] = timeout
    if stream:
        base_kw["stdout"] = None
        base_kw["stderr"] = None
        try:
            return subprocess.run(cmd, **base_kw)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(_format_timeout_error(cmd, timeout, e)) from e
    base_kw["capture_output"] = True
    base_kw["text"] = True
    try:
        return subprocess.run(cmd, **base_kw)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(_format_timeout_error(cmd, timeout, e)) from e

import chromadb
import torch
from sentence_transformers import SentenceTransformer

from nemotron_ab.campaign_assets import payload_has_any_image
from nemotron_ab.config import get_embed_model_name
from nemotron_ab.persona_filter_schema import retrieval_fanout_multiplier
from nemotron_ab.persona_where import chroma_where_and, district_prefix_keyword


SCRIPT_PATH = ROOT_DIR / "scripts" / "ab_validator.py"
OUTPUT_BASE = ROOT_DIR / "outputs" / "jobs"
_RETRIEVAL_MODEL = None


def _resolve_python_executable() -> str:
    """레거시 서브프로세스용 파이썬 실행 경로.

    우선순위: 1) NEMOTRON_AB_PY 환경변수, 2) ./venv/bin/python, 3) 현재 sys.executable.
    OSS 배포 시 사용자의 venv 위치가 다를 수 있어 환경변수 오버라이드를 제공합니다.
    """
    import sys as _sys

    env = os.environ.get("NEMOTRON_AB_PY", "").strip()
    if env:
        return env
    candidate = ROOT_DIR / "venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return _sys.executable


def _make_campaign_payload(job_id: int, payload: Dict) -> List[Dict]:
    camp = {
        "id": f"job_{job_id}",
        "context": str(payload.get("context", "") or ""),
        "text_a": payload.get("text_a", ""),
        "text_b": payload.get("text_b", ""),
    }
    if payload.get("image_a"):
        camp["image_a"] = payload["image_a"]
    if payload.get("image_b"):
        camp["image_b"] = payload["image_b"]
    return [camp]


def _retrieve_filtered_personas(payload: Dict, max_personas: int) -> List[Dict]:
    import os

    if os.environ.get("PERSONA_RETRIEVE_BACKEND", "").strip().lower() == "langchain_chroma":
        from app.chroma_langchain import retrieve_personas_langchain

        rk = int(payload.get("retrieval_k_per_bucket") or 80)
        rk = max(20, min(500, rk))
        return retrieve_personas_langchain(payload, max_personas=max_personas, k=rk)

    db_path = str((ROOT_DIR / "persona_db").resolve())
    collection_name = "marketing_personas"
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_collection(name=collection_name)
    global _RETRIEVAL_MODEL
    if _RETRIEVAL_MODEL is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _RETRIEVAL_MODEL = SentenceTransformer(get_embed_model_name(), device=device)

    persona_filter = payload["persona_filter"]
    where = chroma_where_and(persona_filter)
    occ_needle = str(persona_filter.get("occupation_contains", "") or "").strip()
    district_kw = district_prefix_keyword(persona_filter)

    query_text = " ".join(
        [
            str(payload.get("context", "") or ""),
            str(payload.get("text_a", "") or ""),
            str(payload.get("text_b", "") or ""),
        ]
    ).strip()
    if payload_has_any_image(payload):
        query_text = f"{query_text} 이미지 크리에이티브 포함".strip()
    rk = int(payload.get("retrieval_k_per_bucket") or 80)
    rk = max(20, min(500, rk))
    base_n = max(rk, max_personas, 20)
    mult = retrieval_fanout_multiplier(persona_filter)
    n_results = min(2000, max(base_n * mult, base_n))
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
        if len(rows) >= max_personas:
            break
        row = dict(meta or {})
        row["uuid"] = ids[idx] if idx < len(ids) else f"p-{idx}"
        row["persona"] = docs[idx] if idx < len(docs) else ""
        # validator 정규화를 위한 최소 필드 보정
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

    # district 부분일치 조건은 벡터 상위 샘플에서 누락될 수 있어, 비었으면 지역 우선 스캔으로 보강.
    if not rows and district_kw:
        offset = 0
        page = 1000
        while len(rows) < max_personas:
            got = collection.get(where=where, limit=page, offset=offset, include=["metadatas", "documents"])
            g_ids = got.get("ids") or []
            g_docs = got.get("documents") or []
            g_metas = got.get("metadatas") or []
            if not g_metas:
                break
            for idx, meta in enumerate(g_metas):
                if len(rows) >= max_personas:
                    break
                row = dict(meta or {})
                row["uuid"] = g_ids[idx] if idx < len(g_ids) else f"fallback-{offset+idx}"
                row["persona"] = g_docs[idx] if idx < len(g_docs) else ""
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
            if len(g_metas) < page:
                break
            offset += len(g_metas)
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

    evaluator = str(payload.get("evaluator") or "mock")
    cmd = [
        _resolve_python_executable(),
        str(SCRIPT_PATH),
        "--persona-source",
        "file",
        "--persona-file",
        str(persona_file),
        "--campaign-file",
        str(campaign_file),
        "--profile",
        payload.get("profile") or "small",
        "--output-dir",
        str(output_dir),
        "--evaluator",
        evaluator,
        "--eval-concurrency",
        str(payload.get("eval_concurrency") or 2),
        "--max-personas",
        str(max_personas),
    ]
    # ollama 경로일 때만 모델 정보를 전달. llm_model 우선, 레거시 ollama_model 폴백.
    if evaluator == "ollama":
        llm_model = str(payload.get("llm_model") or payload.get("ollama_model") or "").strip()
        if llm_model:
            cmd.extend(["--ollama-model", llm_model])
    completed = _run_ab_validator_subprocess(cmd)
    if completed.returncode != 0:
        if _subprocess_stream_output():
            raise RuntimeError(
                f"validator 종료 코드 {completed.returncode} "
                f"({_ENV_SUBPROCESS_STREAM}=1 이라 stdout/stderr는 캡처되지 않음)"
            )
        raise RuntimeError(_format_subprocess_failure(completed, cmd))

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
