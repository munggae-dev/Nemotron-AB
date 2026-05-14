"""LLM 호출에 사용할 프롬프트 프로파일 / 길이 가드 헬퍼.

두 가지 책임:

1. **프로파일 해석 (`resolve_prompt_profile`)**
   - `"full"`: 페르소나 raw 를 그대로 사용. 사용자 설정 우선.
   - `"compact"`: 핵심 필드만(`age/sex/occupation/province/district`) 화이트리스트로 남기고,
     `max_reason_chars` 와 `response_format_json` 을 강제해 토큰을 줄인다.

2. **페르소나 뷰 잘라내기 (`truncate_persona_view`)**
   - JSON 직렬화 길이가 `max_chars` 를 넘으면, 긴 문자열 필드 → 짧은 필드 순으로
     선택적으로 줄여서 한도 안으로 맞춘다.

서버 가드 기본값은 환경 변수로 오버라이드할 수 있어, 운영자가 모델/하드웨어에 맞춰 조정 가능하다.

  - `LLM_DEFAULT_PROMPT_PROFILE` (full|compact)
  - `LLM_DEFAULT_MAX_PERSONA_CHARS` (int)
  - `LLM_DEFAULT_MAX_CONTEXT_CHARS` (int)
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# 상수 / 기본값
# ---------------------------------------------------------------------------

VALID_PROFILES = ("full", "compact")

# compact 모드에서 노출하는 핵심 필드 (Nemotron-Personas-Korea 스키마 기준)
COMPACT_PERSONA_FIELDS: tuple = (
    "age",
    "sex",
    "occupation",
    "province",
    "district",
)

# compact 모드 reason 글자 수 상한 (사용자 입력이 더 작으면 그것을 따른다)
COMPACT_REASON_CAP = 40

# 사용자가 별도 지정하지 않을 때의 기본값
DEFAULT_PROFILE = "full"
DEFAULT_MAX_PERSONA_CHARS = 1500
DEFAULT_MAX_CONTEXT_CHARS = 4000

ENV_PROFILE = "LLM_DEFAULT_PROMPT_PROFILE"
ENV_MAX_PERSONA = "LLM_DEFAULT_MAX_PERSONA_CHARS"
ENV_MAX_CONTEXT = "LLM_DEFAULT_MAX_CONTEXT_CHARS"


# ---------------------------------------------------------------------------
# 프로파일 해석
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedPromptProfile:
    """프로파일 해석 결과.

    Attributes:
        profile: 정규화된 이름 ("full" | "compact").
        persona_fields: 화이트리스트로 노출할 페르소나 키 (None 이면 전체).
        persona_drop_fields: 블랙리스트 (화이트리스트가 있을 때는 적용 안 됨).
        max_reason_chars: 사용자 지정 또는 compact 상한.
        response_format_json: JSON 응답 강제 여부.
    """

    profile: str
    persona_fields: list[str] | None
    persona_drop_fields: list[str] | None
    max_reason_chars: int
    response_format_json: bool


def normalize_profile(value: str | None) -> str:
    name = str(value or "").strip().lower()
    if name in VALID_PROFILES:
        return name
    return default_profile()


def default_profile() -> str:
    env = os.environ.get(ENV_PROFILE, "").strip().lower()
    return env if env in VALID_PROFILES else DEFAULT_PROFILE


def default_max_persona_chars() -> int:
    raw = os.environ.get(ENV_MAX_PERSONA, "").strip()
    try:
        return int(raw) if raw else DEFAULT_MAX_PERSONA_CHARS
    except ValueError:
        return DEFAULT_MAX_PERSONA_CHARS


def default_max_context_chars() -> int:
    raw = os.environ.get(ENV_MAX_CONTEXT, "").strip()
    try:
        return int(raw) if raw else DEFAULT_MAX_CONTEXT_CHARS
    except ValueError:
        return DEFAULT_MAX_CONTEXT_CHARS


def resolve_prompt_profile(
    profile: str | None,
    *,
    user_max_reason_chars: int = 80,
    user_response_format_json: bool = False,
    user_persona_fields: Sequence[str] | None = None,
    user_persona_drop_fields: Sequence[str] | None = None,
) -> ResolvedPromptProfile:
    """프로파일을 적용해 최종 평가 파라미터를 결정한다.

    사용자가 명시적으로 지정한 `user_persona_fields` 는 항상 우선한다 — 운영자가
    실험적으로 특정 필드 셋을 강제할 수 있게 하기 위함.
    """
    name = normalize_profile(profile)

    if name == "compact":
        fields = list(user_persona_fields) if user_persona_fields else list(COMPACT_PERSONA_FIELDS)
        max_reason = min(int(user_max_reason_chars or COMPACT_REASON_CAP), COMPACT_REASON_CAP)
        return ResolvedPromptProfile(
            profile="compact",
            persona_fields=fields,
            persona_drop_fields=None,
            max_reason_chars=max(1, max_reason),
            response_format_json=True,
        )

    # full
    fields = list(user_persona_fields) if user_persona_fields else None
    drop = list(user_persona_drop_fields) if user_persona_drop_fields else None
    return ResolvedPromptProfile(
        profile="full",
        persona_fields=fields,
        persona_drop_fields=drop,
        max_reason_chars=max(1, int(user_max_reason_chars or 80)),
        response_format_json=bool(user_response_format_json),
    )


# ---------------------------------------------------------------------------
# 페르소나 뷰 절단
# ---------------------------------------------------------------------------


def _json_len(view: Mapping[str, Any]) -> int:
    return len(json.dumps(view, ensure_ascii=False))


def truncate_persona_view(
    view: Mapping[str, Any],
    max_chars: int,
    *,
    suffix: str = "…",
) -> dict[str, Any]:
    """페르소나 뷰의 JSON 직렬화 길이를 `max_chars` 이하로 줄인다.

    전략 (필드를 통째로 버리지 않고 *내용*만 자른다):

    1. 직렬화 결과가 한도 안이면 그대로 반환.
    2. 그렇지 않으면 문자열 값 중 긴 것부터 절반씩 줄여가며 한도에 맞춘다.
    3. 마지막까지 줄여도 초과하면, 가장 긴 문자열을 1자(+suffix) 까지 자른다.

    이 절단은 dict 의 키 집합 자체를 바꾸지 않는다 — 다운스트림에서
    필드 누락으로 분기되는 로직을 방지하기 위함.
    """
    if not isinstance(view, dict) or max_chars <= 0:
        return dict(view) if isinstance(view, dict) else {}

    out: dict[str, Any] = dict(view)
    if _json_len(out) <= max_chars:
        return out

    # 문자열 길이 내림차순으로 후보 정렬
    str_keys = [k for k, v in out.items() if isinstance(v, str)]
    str_keys.sort(key=lambda k: len(out[k]), reverse=True)

    # 점진적으로 가장 긴 문자열을 절반씩 줄여간다
    for _ in range(64):  # 안전 상한
        if _json_len(out) <= max_chars:
            return out
        if not str_keys:
            break
        # 매 반복마다 현재 가장 긴 문자열을 찾는다
        longest = max(str_keys, key=lambda k: len(out[k]))
        cur = out[longest]
        if len(cur) <= 1:
            str_keys.remove(longest)
            continue
        new_len = max(1, len(cur) // 2)
        out[longest] = cur[:new_len] + suffix

    # 그래도 초과하면 가장 긴 문자열을 추가로 더 자른다 (강제 수렴)
    while _json_len(out) > max_chars:
        longest_key = None
        longest_val = -1
        for k, v in out.items():
            if isinstance(v, str) and len(v) > longest_val:
                longest_key = k
                longest_val = len(v)
        if longest_key is None or longest_val <= len(suffix):
            break
        cur = out[longest_key]
        out[longest_key] = cur[: max(1, len(cur) - max(8, longest_val // 4))] + suffix

    return out
