"""FastAPI 진입점 (uvicorn backend.main:app).

구현은 backend.app · backend.routers · backend.services · backend.schemas 로 분리되어 있습니다.
"""
from __future__ import annotations

from backend.app import create_app
from backend.schemas.jobs import ImageRefIn, JobCloneOptions, JobCreate, PersonaFilterIn
from backend.services.job_payload import payload_from_create as _payload_from_create

app = create_app()

# 하위 호환: 기존 테스트·스크립트가 backend.main 에서 스키마/헬퍼를 import
__all__ = [
    "app",
    "create_app",
    "PersonaFilterIn",
    "ImageRefIn",
    "JobCreate",
    "JobCloneOptions",
    "_payload_from_create",
]
