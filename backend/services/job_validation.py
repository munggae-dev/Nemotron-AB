"""Job 생성·페르소나 필터 입력 검증."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from backend.schemas.jobs import ImageRefIn
from nemotron_ab.campaign_assets import validate_asset_ref_exists
from nemotron_ab.persona_filter_schema import FIELD_LABEL_KO, FILTER_ENUM_LOOKUP


def optional_image_payload(ref: ImageRefIn | None) -> dict[str, str] | None:
    if ref is None:
        return None
    t = ref.type.strip()
    v = ref.value.strip()
    if not v:
        return None
    if t not in ("url", "asset_ref"):
        raise HTTPException(400, "image_a/image_b.type은 url 또는 asset_ref여야 합니다")
    return {"type": t, "value": v}


def validate_variant_inputs(text_s: str, img: ImageRefIn | None, label: str) -> None:
    has_text = bool(text_s.strip())
    has_img = img is not None and bool(img.value.strip())
    if not has_text and not has_img:
        raise HTTPException(400, f"{label}에는 텍스트 또는 이미지 중 하나 이상 필요합니다")


def validate_image_in(ref: ImageRefIn | None) -> None:
    if ref is None or not ref.value.strip():
        return
    if ref.type.strip() == "url":
        v = ref.value.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise HTTPException(400, "이미지 URL은 http:// 또는 https:// 로 시작해야 합니다")
    elif ref.type.strip() == "asset_ref":
        try:
            validate_asset_ref_exists(ref.value.strip())
        except FileNotFoundError as e:
            raise HTTPException(400, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    else:
        raise HTTPException(400, "image type은 url 또는 asset_ref만 허용됩니다")


def validate_nemotron_persona_filter_enums(pf: Mapping[str, Any]) -> None:
    for key, allowed in FILTER_ENUM_LOOKUP.items():
        v = str(pf.get(key, "") or "").strip()
        if v and v not in allowed:
            label = FIELD_LABEL_KO.get(key, key)
            raise HTTPException(
                400,
                f'persona_filter "{label}" 값이 허용 목록에 없습니다. '
                "GET /meta/persona-filters 의 options 를 사용하세요.",
            )
