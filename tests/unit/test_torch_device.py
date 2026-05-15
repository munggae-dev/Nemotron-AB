"""nemotron_ab.torch_device 단위 테스트."""
from __future__ import annotations

import pytest

from nemotron_ab import torch_device as td


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"),
    [
        (True, False, "cuda"),
        (False, True, "mps"),
        (False, False, "cpu"),
        (True, True, "cuda"),
    ],
)
def test_pick_accel_device(monkeypatch, cuda: bool, mps: bool, expected: str):
    monkeypatch.setattr(td, "is_cuda_available", lambda: cuda)
    monkeypatch.setattr(td, "is_mps_available", lambda: mps)
    assert td.pick_accel_device() == expected


def test_resolve_torch_device_auto(monkeypatch):
    monkeypatch.setattr(td, "pick_accel_device", lambda: "mps")
    assert td.resolve_torch_device("auto") == "mps"


def test_resolve_mps_unavailable_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(td, "is_mps_available", lambda: False)
    assert td.resolve_torch_device("mps") == "cpu"


def test_should_use_fp16_auto():
    assert td.should_use_fp16("cuda", "auto") is True
    assert td.should_use_fp16("mps", "auto") is False
    assert td.should_use_fp16("cpu", "auto") is False


def test_should_use_fp16_on_mps_warns(capsys):
    assert td.should_use_fp16("mps", "on") is False
    assert "MPS" in capsys.readouterr().out


def test_resolve_chroma_lc_device_empty(monkeypatch):
    monkeypatch.setattr(td, "pick_accel_device", lambda: "mps")
    assert td.resolve_chroma_lc_device("") == "mps"
    assert td.resolve_chroma_lc_device("auto") == "mps"
