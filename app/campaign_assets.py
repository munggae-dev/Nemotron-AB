"""캠페인 이미지 자산: 스테이징 업로드, job별 승격(guard path), LLM용 data URL 해석."""
from __future__ import annotations

import base64
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_STAGING = REPO_ROOT / "outputs" / "staging"
OUTPUT_JOBS = REPO_ROOT / "outputs" / "jobs"
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_URL_FETCH_BYTES = 2 * 1024 * 1024
_URL_FETCH_TIMEOUT_SEC = 30

def extension_from_filename(filename: str) -> str:
    suf = Path(filename).suffix.lower()
    return suf if suf in ALLOWED_SUFFIXES else ".webp"


def save_upload_to_staging(data: bytes, filename: str) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"파일 크기는 {MAX_UPLOAD_BYTES}바이트 이하여야 합니다")
    OUTPUT_STAGING.mkdir(parents=True, exist_ok=True)
    ext = extension_from_filename(filename)
    name = f"{uuid.uuid4().hex}{ext}"
    path = OUTPUT_STAGING / name
    path.write_bytes(data)
    return f"staging/{name}"


def staging_relative_path(asset_ref_value: str) -> Path:
    v = asset_ref_value.strip().replace("\\", "/")
    if not v.startswith("staging/"):
        raise ValueError("asset_ref는 staging/ 로 시작해야 합니다")
    tail = v[len("staging/") :].lstrip("/")
    if not tail or ".." in tail.split("/"):
        raise ValueError("유효하지 않은 asset_ref")
    return OUTPUT_STAGING / tail


def validate_asset_ref_exists(asset_ref_value: str) -> None:
    p = staging_relative_path(asset_ref_value)
    if not p.is_file():
        raise FileNotFoundError(f"스테이징 파일 없음: {asset_ref_value}")


def _job_assets_dir(job_id: int) -> Path:
    return OUTPUT_JOBS / f"job_{job_id}" / "assets"


def promote_asset_to_job(job_id: int, variant: Literal["a", "b"], ref: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """staging/asset_ref → outputs/jobs/job_{id}/assets/{a|b}.{ext}. URL·path는 그대로 반환."""
    if ref is None:
        return None
    if not isinstance(ref, dict):
        raise ValueError("image ref는 객체여야 합니다")
    t = str(ref.get("type", "")).strip()
    v = str(ref.get("value", "")).strip()
    if not t or not v:
        return None
    if t == "url":
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("이미지 URL은 http(s)여야 합니다")
        return {"type": "url", "value": v}
    if t == "path":
        rel = Path(v.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("유효하지 않은 저장 경로")
        full = REPO_ROOT / rel
        if not full.is_file():
            raise FileNotFoundError(f"이미지 파일 없음: {v}")
        return {"type": "path", "value": str(rel).replace("\\", "/")}
    if t == "asset_ref":
        src = staging_relative_path(v)
        if not src.is_file():
            raise FileNotFoundError(f"스테이징 파일 없음: {v}")
        dest_dir = _job_assets_dir(job_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        suf = src.suffix if src.suffix.lower() in ALLOWED_SUFFIXES else ".webp"
        dest = dest_dir / f"{variant}{suf}"
        shutil.move(str(src), str(dest))
        rel = dest.relative_to(REPO_ROOT)
        return {"type": "path", "value": str(rel).replace("\\", "/")}
    raise ValueError(f"알 수 없는 image ref type: {t}")


def normalize_job_payload_images(job_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out["image_a"] = promote_asset_to_job(job_id, "a", out.get("image_a"))
    out["image_b"] = promote_asset_to_job(job_id, "b", out.get("image_b"))
    return out


def _guess_mime_suffix(suffix: str) -> str:
    mime, _ = mimetypes.guess_type(f"x{suffix}")
    return mime or "application/octet-stream"


def image_ref_to_data_url(ref: Dict[str, Any]) -> str:
    """LangChain/Ollama 멀티모달용 data:image/...;base64,..."""
    t = str(ref.get("type", ""))
    v = str(ref.get("value", "")).strip()
    if t == "path":
        path = (REPO_ROOT / v.replace("\\", "/")).resolve()
        if not str(path).startswith(str(REPO_ROOT.resolve())):
            raise ValueError("경로 이탈")
        data = path.read_bytes()
        if len(data) > MAX_URL_FETCH_BYTES:
            raise ValueError("이미지가 너무 큽니다")
        mime = _guess_mime_suffix(path.suffix.lower())
        b64 = base64.standard_b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    if t == "url":
        req = Request(v, headers={"User-Agent": "nemotron-campaign-validator/1.0"})
        with urlopen(req, timeout=_URL_FETCH_TIMEOUT_SEC) as resp:
            data = resp.read(MAX_URL_FETCH_BYTES + 1)
            ctype = resp.headers.get_content_type() if hasattr(resp, "headers") else None
        if len(data) > MAX_URL_FETCH_BYTES:
            raise ValueError("다운로드 이미지가 너무 큽니다")
        mime = ctype.split(";")[0].strip() if ctype else "application/octet-stream"
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        b64 = base64.standard_b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    raise ValueError(f"data URL 변환 불가 type={t}")


def resolve_image_file_path(ref: Dict[str, Any]) -> Optional[Path]:
    """GET /jobs/.../images 서빙용 로컬 파일 경로."""
    if str(ref.get("type", "")) != "path":
        return None
    v = str(ref.get("value", "")).strip()
    path = (REPO_ROOT / v.replace("\\", "/")).resolve()
    root = REPO_ROOT.resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        return None
    return path


def payload_has_any_image(payload: Dict[str, Any]) -> bool:
    for key in ("image_a", "image_b"):
        ref = payload.get(key)
        if isinstance(ref, dict) and str(ref.get("value", "")).strip():
            return True
    return False


def campaign_has_any_image(campaign: Dict[str, Any]) -> bool:
    for key in ("image_a", "image_b"):
        ref = campaign.get(key)
        if isinstance(ref, dict) and str(ref.get("value", "")).strip():
            return True
    return False


def mock_image_seed_fragment(campaign: Dict[str, Any]) -> str:
    parts = []
    for key in ("image_a", "image_b"):
        ref = campaign.get(key)
        if isinstance(ref, dict):
            parts.append(f"{key}:{ref.get('type')}:{ref.get('value')}")
    return "|".join(parts)
