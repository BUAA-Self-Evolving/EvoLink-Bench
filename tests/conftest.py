"""Synthetic package metadata for config-generation unit tests, never real data."""
import json

import pytest


@pytest.fixture(autouse=True)
def synthetic_v5_config_plan(request, tmp_path, monkeypatch):
    if request.path.name not in {"test_matrix_portability.py", "test_skillopt_baseline.py"}:
        return
    from tools import prepare_matrix_configs as module

    original = module._v5_tau2_stream_ids
    streams = [
        "intra_tau2_blocked_01", "intra_tau2_interleaved_01", "intra_tau2_delayed_01",
        "cross_blocked_01", "cross_interleaved_01", "cross_delayed_01",
        "cross_transfer_interleaved_01", "cross_transfer_delayed_01",
    ]
    root = tmp_path / "synthetic-plan"
    plan = root / "benchmarks/current/L2_Demo_V5/stream_plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"streams": [
        {"stream_id": stream, "capabilities": [{"capability_id": "tau2.synthetic"}]}
        for stream in streams
    ]}), encoding="utf-8")
    monkeypatch.setattr(module, "_v5_tau2_stream_ids", lambda _repo: original(root))
