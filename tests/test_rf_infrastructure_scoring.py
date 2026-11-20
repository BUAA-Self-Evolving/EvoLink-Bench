import json
from pathlib import Path

import pytest

from evolink_bench.baselines.base import BaselineReply, UsageDetails
from evolink_bench.runner import Runner
from evolink_bench.spec import load_spec


@pytest.mark.parametrize("kind", ["native_error", "transport_error", "verifier_error",
                                   "llm_parse_error", "l1_life_judge_parse_error"])
def test_infrastructure_failure_preserves_evidence_without_committing_score(tmp_path, monkeypatch, kind):
    spec = load_spec(Path(__file__).parents[1] / "examples/smoke.json")
    runner = Runner(spec, output_dir=tmp_path, backend="local", agent_mode="scripted",
                    judge_mode="deterministic", fail_fast_infrastructure=True)
    def interact(*args):
        runner.budget.record(17, calls=1)
        if kind == "transport_error":
            raise RuntimeError("injected request timeout")
        return BaselineReply(text="saved partial", usage=UsageDetails(total_tokens=17, api_calls=1),
            raw={"execution_error": {"type": "adapter_deadline"}, "usage_status": "partial_unknown"}
                if kind == "native_error" else None)
    monkeypatch.setattr(runner.runtime, "interact", interact)
    if kind == "verifier_error":
        def evaluate(*args):
            raise RuntimeError("injected verifier transport failure")
        monkeypatch.setattr(runner, "_evaluate", evaluate)
    elif kind.endswith("parse_error"):
        from evolink_bench.verifier import CheckResult
        monkeypatch.setattr(runner, "_evaluate", lambda *a: CheckResult(
            0, False, "invalid judge output", {"type": kind}))
    with pytest.raises(RuntimeError, match="evaluation infrastructure failed"):
        runner.run(spec.flows[0])
    assert not list(tmp_path.glob("*/summary.json"))
    assert not list(tmp_path.glob("_checkpoints/*/t*/completed_turns.json"))
    records = [json.loads(x) for x in next(tmp_path.glob("*/live_trace.jsonl")).read_text().splitlines()]
    assert len(records) == 1
    assert runner.budget.used == 17 and runner.budget.calls == 1
    if kind == "native_error":
        assert records[0]["response"] == "saved partial"
        assert records[0]["verifier_details"]["type"] == "native_execution_error"


def test_declared_work_limit_remains_a_scored_outcome_not_a_transport_retry(tmp_path, monkeypatch):
    spec = load_spec(Path(__file__).parents[1] / "examples/smoke.json")
    runner = Runner(spec, output_dir=tmp_path, backend="local", agent_mode="scripted",
                    judge_mode="deterministic", fail_fast_infrastructure=True)
    calls = []
    def interact(*args):
        calls.append(1)
        return BaselineReply(raw={"limit_exhausted": True, "limit_reasons": ["max_tool_calls"]})
    monkeypatch.setattr(runner.runtime, "interact", interact)
    result = runner.run(spec.flows[0])
    assert len(calls) == 2
    assert all(x["score"] == 0 and x["passed"] is False for x in result["turns"])
