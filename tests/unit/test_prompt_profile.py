"""Phase 2: prompt_profile 해석 + persona_view 길이 캡."""
from __future__ import annotations

import json

import pytest

from nemotron_ab.prompt_profile import (
    COMPACT_PERSONA_FIELDS,
    COMPACT_REASON_CAP,
    DEFAULT_MAX_PERSONA_CHARS,
    DEFAULT_PROFILE,
    ENV_MAX_PERSONA,
    ENV_PROFILE,
    default_max_persona_chars,
    default_profile,
    normalize_profile,
    resolve_prompt_profile,
    truncate_persona_view,
)


# ---------------------------------------------------------------------------
# 프로파일 해석
# ---------------------------------------------------------------------------


def test_normalize_profile_accepts_known_values() -> None:
    assert normalize_profile("full") == "full"
    assert normalize_profile("compact") == "compact"
    assert normalize_profile("COMPACT") == "compact"
    assert normalize_profile(" full ") == "full"


def test_normalize_profile_defaults_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    assert normalize_profile(None) == DEFAULT_PROFILE
    assert normalize_profile("") == DEFAULT_PROFILE
    assert normalize_profile("bogus") == DEFAULT_PROFILE


def test_default_profile_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PROFILE, "compact")
    assert default_profile() == "compact"
    monkeypatch.setenv(ENV_PROFILE, "invalid")
    assert default_profile() == DEFAULT_PROFILE


def test_resolve_full_keeps_user_settings() -> None:
    res = resolve_prompt_profile(
        "full",
        user_max_reason_chars=80,
        user_response_format_json=False,
    )
    assert res.profile == "full"
    assert res.persona_fields is None  # raw 사용
    assert res.persona_drop_fields is None
    assert res.max_reason_chars == 80
    assert res.response_format_json is False


def test_resolve_full_with_explicit_user_fields() -> None:
    res = resolve_prompt_profile(
        "full",
        user_max_reason_chars=60,
        user_response_format_json=True,
        user_persona_fields=["age", "sex"],
        user_persona_drop_fields=["uuid"],
    )
    assert res.persona_fields == ["age", "sex"]  # 화이트리스트 우선
    assert res.persona_drop_fields == ["uuid"]
    assert res.response_format_json is True


def test_resolve_compact_forces_core_fields_and_json() -> None:
    res = resolve_prompt_profile(
        "compact",
        user_max_reason_chars=200,  # 200 -> compact 상한(40)으로 잘림
        user_response_format_json=False,
    )
    assert res.profile == "compact"
    assert res.persona_fields == list(COMPACT_PERSONA_FIELDS)
    assert res.persona_drop_fields is None
    assert res.max_reason_chars == COMPACT_REASON_CAP
    assert res.response_format_json is True  # 강제


def test_resolve_compact_respects_smaller_user_reason() -> None:
    res = resolve_prompt_profile("compact", user_max_reason_chars=20)
    assert res.max_reason_chars == 20  # 사용자가 더 작게 주면 그대로 따른다


def test_resolve_compact_user_fields_override() -> None:
    res = resolve_prompt_profile(
        "compact",
        user_persona_fields=["age", "occupation"],
    )
    assert res.persona_fields == ["age", "occupation"]


def test_resolve_unknown_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    res = resolve_prompt_profile("nonsense", user_max_reason_chars=80)
    assert res.profile == DEFAULT_PROFILE


# ---------------------------------------------------------------------------
# 길이 캡
# ---------------------------------------------------------------------------


def test_default_max_persona_chars_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_MAX_PERSONA, raising=False)
    assert default_max_persona_chars() == DEFAULT_MAX_PERSONA_CHARS
    monkeypatch.setenv(ENV_MAX_PERSONA, "800")
    assert default_max_persona_chars() == 800
    monkeypatch.setenv(ENV_MAX_PERSONA, "not-a-number")
    assert default_max_persona_chars() == DEFAULT_MAX_PERSONA_CHARS


def test_truncate_passthrough_when_within_limit() -> None:
    view = {"age": 30, "sex": "여자", "note": "짧은 메모"}
    out = truncate_persona_view(view, max_chars=200)
    assert out == view


def test_truncate_preserves_keys_and_caps_size() -> None:
    long_text = "한국어로 길게 쓰인 페르소나 노트입니다. " * 20  # ~600자
    view = {
        "age": 30,
        "sex": "여자",
        "occupation": "디자이너",
        "note": long_text,
        "background": long_text,
    }
    out = truncate_persona_view(view, max_chars=200)
    assert set(out.keys()) == set(view.keys()), "키 집합은 유지되어야 한다"
    assert len(json.dumps(out, ensure_ascii=False)) <= 200
    # 짧은 스칼라 필드는 그대로
    assert out["age"] == 30
    assert out["sex"] == "여자"


def test_truncate_handles_zero_or_negative_cap() -> None:
    view = {"age": 30, "sex": "여자"}
    assert truncate_persona_view(view, max_chars=0) == view
    assert truncate_persona_view(view, max_chars=-1) == view


def test_truncate_handles_non_dict() -> None:
    assert truncate_persona_view([], max_chars=100) == {}  # type: ignore[arg-type]
    assert truncate_persona_view("not-a-dict", max_chars=100) == {}  # type: ignore[arg-type]
