"""런타임 설정 상수와 환경변수 해석 유틸.

오픈소스 배포에서 사용자가 임베딩 모델을 손쉽게 바꿀 수 있도록 단일 진입점을 둔다.
"""
from __future__ import annotations

import os

# 기본 임베딩 모델: BAAI/bge-m3 (MIT 라이선스, 다국어/한국어 우수, 1024차원).
# 이전 기본값 `jhgan/ko-sroberta-multitask` (CC BY-SA 4.0, 768차원) 에서 변경.
# 변경 시 persona_db 는 차원/공간이 달라 **반드시 재빌드** 해야 한다.
DEFAULT_EMBED_MODEL = "BAAI/bge-m3"

# 임베딩 모델 환경변수 이름.
ENV_EMBED_MODEL = "EMBED_MODEL_NAME"


def get_embed_model_name(override: str | None = None) -> str:
    """임베딩 모델 이름을 결정한다.

    우선순위: 함수 인자 `override` > 환경변수 `EMBED_MODEL_NAME` > `DEFAULT_EMBED_MODEL`.
    """
    if override and override.strip():
        return override.strip()
    env = os.environ.get(ENV_EMBED_MODEL, "").strip()
    if env:
        return env
    return DEFAULT_EMBED_MODEL
