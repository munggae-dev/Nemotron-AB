#!/usr/bin/env python3
"""
로컬 Ollama 멀티모달(비전) 지원 여부를 빠르게 확인합니다.

  # 저장소 루트에서 (venv 활성화 권장)
  ./venv/bin/python script/test_ollama_multimodal.py --model gemma4:e4b-it-q4_K_M
  ./venv/bin/python script/test_ollama_multimodal.py --model llava --backend langchain

- --backend rest: POST /api/chat (Ollama 네이티브)
- --backend langchain: 앱 워커와 동일한 HumanMessage 멀티파트 + ChatOllama
- 이미지 미지정 시 1×1 픽셀 PNG(내장 base64)로 최소 테스트
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]

# 검증된 최소 PNG (투명 1×1)
_MIN_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ollama 멀티모달(이미지) 스모크 테스트")
    p.add_argument("--model", default="gemma4:e4b-it-q4_K_M", help="ollama list 에 보이는 모델 태그와 동일")
    p.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama 베이스 URL",
    )
    p.add_argument(
        "--image",
        type=Path,
        default=None,
        help="테스트 PNG/JPEG 등 (미지정 시 1×1 PNG 사용)",
    )
    p.add_argument(
        "--prompt",
        default="이미지가 주어졌나요? 보이면 '예' 한 글자, 아니면 '아니오' 한 글자만 답해.",
        help="모델에 보낼 질문",
    )
    p.add_argument(
        "--backend",
        choices=("rest", "langchain", "both"),
        default="both",
        help="호출 방식",
    )
    p.add_argument("--timeout-sec", type=int, default=120)
    return p.parse_args()


def _image_b64(path: Path | None) -> Tuple[str, str]:
    if path is None:
        return base64.standard_b64decode(_MIN_PNG_B64), "builtin-1x1.png"
    if not path.is_file():
        raise FileNotFoundError(str(path))
    data = path.read_bytes()
    return data, path.name


def test_rest(base_url: str, model: str, image_b64: str, prompt: str, timeout: int) -> str:
    url = base_url.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    msg = raw.get("message") or {}
    content = msg.get("content") or ""
    return str(content).strip()


def test_langchain(base_url: str, model: str, data_url: str, prompt: str) -> str:
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    try:
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise RuntimeError(
            "langchain_core / langchain_ollama 가 없습니다. "
            "`pip install -r backend/requirements.txt` 후 다시 실행하세요."
        ) from e

    llm = ChatOllama(model=model, temperature=0.1, base_url=base_url.rstrip("/"))
    parts = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    resp = llm.invoke([HumanMessage(content=parts)])
    return str(resp.content or "").strip()


def main() -> int:
    args = parse_args()
    try:
        blob, label = _image_b64(args.image)
    except FileNotFoundError as e:
        print(f"[FAIL] 이미지: {e}", file=sys.stderr)
        return 2

    b64 = base64.standard_b64encode(blob).decode("ascii")
    mime = "image/png"
    if args.image and args.image.suffix.lower() in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif args.image and args.image.suffix.lower() == ".webp":
        mime = "image/webp"
    elif args.image and args.image.suffix.lower() == ".gif":
        mime = "image/gif"
    data_url = f"data:{mime};base64,{b64}"

    print(f"모델: {args.model}")
    print(f"이미지: {label} ({len(blob)} bytes)")
    print(f"base-url: {args.base_url}")

    backends = []
    if args.backend in ("rest", "both"):
        backends.append("rest")
    if args.backend in ("langchain", "both"):
        backends.append("langchain")

    ok_any = False
    for name in backends:
        print(f"\n--- [{name}] ---")
        try:
            if name == "rest":
                out = test_rest(
                    args.base_url,
                    args.model,
                    b64,
                    args.prompt,
                    args.timeout_sec,
                )
            else:
                out = test_langchain(
                    args.base_url,
                    args.model,
                    data_url,
                    args.prompt,
                )
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:2000]
            print(f"[FAIL] HTTP {e.code}: {err_body}", file=sys.stderr)
            continue
        except urllib.error.URLError as e:
            print(f"[FAIL] 네트워크: {e}", file=sys.stderr)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {type(e).__name__}: {e}", file=sys.stderr)
            continue

        print(out or "(빈 응답)")
        if out:
            ok_any = True

    if ok_any:
        print("\n[OK] 적어도 한 경로에서 응답을 받았습니다. 멀티모달 파이프라인 테스트 가능 여부는 모델/버전별로 추가 확인하세요.")
        return 0
    print("\n[FAIL] 모든 백엔드 실패 또는 빈 응답입니다.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
