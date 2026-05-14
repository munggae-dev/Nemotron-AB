"""validator_runner 회귀: `ollama_model` 키가 없는 payload 도 KeyError 없이 처리한다.

E2E 검증 도중 발견된 버그(`payload["ollama_model"]` 직접 참조 → KeyError)에 대한 회귀 차단.
실제 ChromaDB / 서브프로세스는 monkeypatch 로 격리한다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest


def _stub_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _write_report(output_dir: Path, job_id: int) -> None:
    """validator 가 생성하는 산출물 형태를 흉내낸다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"job_{job_id}.report.json").write_text(
        json.dumps(
            {
                "report": {
                    "final_winner": "A",
                    "overall": {"count": 1, "win_rate": {"A": 1.0, "B": 0.0}},
                    "key_reasons": ["stub"],
                },
                "runtime": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / f"job_{job_id}.partial.jsonl").write_text("{}\n", encoding="utf-8")


def _patch_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> List[List[str]]:
    """서브프로세스/페르소나 검색/출력 경로를 격리. 호출된 cmd 를 캡처해 반환한다."""
    from nemotron_ab.services import validator_runner as vr

    captured: List[List[str]] = []

    def _fake_retrieve(_payload: Dict[str, Any], *, max_personas: int) -> List[Dict[str, Any]]:
        return [
            {
                "uuid": "p1",
                "persona": "테스트용 페르소나",
                "age": 30,
                "sex": "여자",
                "occupation": "디자이너",
                "province": "서울",
                "district": "강남구",
            }
        ]

    def _fake_subprocess(cmd: List[str]) -> subprocess.CompletedProcess:
        captured.append(list(cmd))
        # validator 가 만들어야 할 산출물을 흉내낸다
        # cmd 안의 --output-dir 다음 값
        out_idx = cmd.index("--output-dir") + 1
        out = Path(cmd[out_idx])
        # job_id 는 부모 디렉토리 이름에서 추출 (job_<id>/result)
        job_id = int(out.parent.name.replace("job_", ""))
        _write_report(out, job_id)
        return _stub_completed(returncode=0)

    monkeypatch.setattr(vr, "_retrieve_filtered_personas", _fake_retrieve)
    monkeypatch.setattr(vr, "_run_ab_validator_subprocess", _fake_subprocess)
    monkeypatch.setattr(vr, "OUTPUT_BASE", tmp_path / "outputs" / "jobs")
    return captured


def test_run_validator_handles_payload_without_ollama_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _patch_runner(monkeypatch, tmp_path)
    from nemotron_ab.services.validator_runner import run_validator

    payload: Dict[str, Any] = {
        "text_a": "A 안",
        "text_b": "B 안",
        "context": "가입 안내",
        "profile": "small",
        "evaluator": "mock",
        "max_personas": 8,
        "eval_concurrency": 2,
        # ollama_model / llm_model 키 모두 없음
        "persona_filter": {"sex": "all", "age_min": 20, "age_max": 50},
    }
    report_path, partial_path, summary = run_validator(job_id=42, payload=payload)

    assert report_path.exists()
    assert partial_path.exists()
    assert summary["final_winner"] == "A"

    assert len(captured) == 1
    cmd = captured[0]
    # mock 경로에서는 --ollama-model 인자가 포함되지 않아야 한다
    assert "--ollama-model" not in cmd
    assert cmd[cmd.index("--evaluator") + 1] == "mock"


def test_run_validator_passes_llm_model_only_for_ollama_evaluator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _patch_runner(monkeypatch, tmp_path)
    from nemotron_ab.services.validator_runner import run_validator

    payload: Dict[str, Any] = {
        "text_a": "A",
        "text_b": "B",
        "context": "ctx",
        "profile": "small",
        "evaluator": "ollama",
        "llm_model": "gemma4:e2b-it-q4_K_M",
        "max_personas": 8,
        "eval_concurrency": 2,
        "persona_filter": {"sex": "all", "age_min": 20, "age_max": 50},
    }
    run_validator(job_id=7, payload=payload)
    cmd = captured[0]
    assert "--ollama-model" in cmd
    assert cmd[cmd.index("--ollama-model") + 1] == "gemma4:e2b-it-q4_K_M"


def test_run_validator_supports_legacy_ollama_model_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """레거시 데이터(`ollama_model`) 가 들어와도 호환 처리되어야 한다."""
    captured = _patch_runner(monkeypatch, tmp_path)
    from nemotron_ab.services.validator_runner import run_validator

    payload: Dict[str, Any] = {
        "text_a": "A",
        "text_b": "B",
        "context": "ctx",
        "profile": "small",
        "evaluator": "ollama",
        "ollama_model": "legacy-model:7b",
        "max_personas": 8,
        "eval_concurrency": 2,
        "persona_filter": {"sex": "all", "age_min": 20, "age_max": 50},
    }
    run_validator(job_id=8, payload=payload)
    cmd = captured[0]
    assert cmd[cmd.index("--ollama-model") + 1] == "legacy-model:7b"
