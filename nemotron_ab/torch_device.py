"""PyTorch/Sentence-Transformers 디바이스 선택 (CUDA / MPS / CPU)."""
from __future__ import annotations

import argparse
from typing import Literal

DEVICE_CHOICES: tuple[str, ...] = ("auto", "cuda", "mps", "cpu")
Fp16Mode = Literal["auto", "on", "off"]


def is_cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def is_mps_available() -> bool:
    try:
        import torch

        return bool(
            getattr(torch.backends, "mps", None) is not None
            and torch.backends.mps.is_available()
        )
    except Exception:  # noqa: BLE001
        return False


def pick_accel_device() -> str:
    """가속 디바이스 우선순위: cuda > mps > cpu."""
    if is_cuda_available():
        return "cuda"
    if is_mps_available():
        return "mps"
    return "cpu"


def resolve_torch_device(device_arg: str) -> str:
    """CLI `--device` / `--retrieval-device` 등을 실제 torch device 문자열로 변환."""
    arg = (device_arg or "auto").strip().lower()
    if arg == "auto":
        return pick_accel_device()
    if arg == "cuda":
        if not is_cuda_available():
            print("[WARN] CUDA를 요청했지만 GPU를 찾지 못했습니다. CPU로 전환합니다.")
            return "cpu"
        return "cuda"
    if arg == "mps":
        if not is_mps_available():
            print("[WARN] MPS를 요청했지만 Apple Silicon GPU를 찾지 못했습니다. CPU로 전환합니다.")
            return "cpu"
        return "mps"
    if arg == "cpu":
        return "cpu"
    raise ValueError(f"지원하지 않는 device: {device_arg!r} (허용: {', '.join(DEVICE_CHOICES)})")


def resolve_chroma_lc_device(env_value: str | None = None) -> str:
    """`CHROMA_LC_DEVICE` 환경변수 → LangChain HuggingFaceEmbeddings `device`.

    - 비우거나 `auto`: cuda > mps > cpu
    - `cuda` / `mps` / `cpu`: 명시 (없으면 경고 후 cpu)
    """
    import os

    raw = (env_value if env_value is not None else os.environ.get("CHROMA_LC_DEVICE", "")).strip().lower()
    if not raw or raw == "auto":
        return pick_accel_device()
    return resolve_torch_device(raw)


def should_use_fp16(device: str, fp16: Fp16Mode) -> bool:
    """FP16 인코딩 여부. MPS는 연산 호환 이슈로 auto 시 비활성(Metal 가속만 사용)."""
    if fp16 == "off":
        return False
    if fp16 == "on":
        if device == "cuda":
            return True
        if device == "mps":
            print("[WARN] MPS에서는 fp16=on 을 권장하지 않습니다. fp32로 진행합니다.")
        return False
    # auto
    return device == "cuda"


def empty_device_cache(device: str) -> None:
    """배치 flush 후 GPU 캐시 비우기 (CUDA/MPS)."""
    try:
        import torch

        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif device == "mps" and is_mps_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def add_device_arg(parser: argparse.ArgumentParser, *names: str, default: str = "auto") -> None:
    """argparse에 `--device` / `--retrieval-device` 스타일 인자 추가."""
    parser.add_argument(
        *names,
        choices=list(DEVICE_CHOICES),
        default=default,
        help="임베딩 디바이스. auto=cuda>mps>cpu 우선순위.",
    )


def prepare_sentence_transformer(model, device: str, fp16: Fp16Mode, max_seq_length: int | None) -> bool:
    """max_seq_length·fp16 적용 후 fp16 사용 여부 반환."""
    if max_seq_length and max_seq_length > 0:
        try:
            model.max_seq_length = max_seq_length
        except (AttributeError, TypeError):
            # model2vec StaticEmbedding 등은 max_seq_length setter 미지원
            pass
    use_fp16 = should_use_fp16(device, fp16)
    if use_fp16:
        try:
            model.half()
        except (AttributeError, TypeError, RuntimeError):
            use_fp16 = False
    return use_fp16
