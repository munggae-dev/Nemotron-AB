"""FastAPI 앱 팩토리."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import health, jobs, meta, notifications


def create_app() -> FastAPI:
    application = FastAPI(title="Nemotron Marketing API", version="0.1.0")
    origins = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router)
    application.include_router(meta.router)
    application.include_router(jobs.router)
    application.include_router(notifications.router)
    return application
