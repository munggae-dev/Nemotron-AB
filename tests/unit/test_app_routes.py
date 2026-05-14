"""V5: FastAPI app 로드 + 핵심 라우트 노출."""
from __future__ import annotations


def test_app_exposes_core_routes(isolated_sqlite) -> None:
    from backend.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    for required in ("/health", "/jobs", "/meta/regions"):
        assert required in paths, f"missing route: {required}"
