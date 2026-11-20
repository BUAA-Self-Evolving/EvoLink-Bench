from pathlib import Path
from types import SimpleNamespace

import pytest

from evolink_bench.l2_agent import L2AgentStreamRunner, _work_limits
from evolink_bench.model import TokenBudget
from evolink_bench.run_conditions import RunCondition


@pytest.mark.parametrize('condition,expected', [
    ('reset', 'disabled'), ('frozen', 'disabled'), ('evolving', 'turn_boundary')])
def test_codex_l2_runtime_obeys_learning_condition(monkeypatch, condition, expected):
    runner = object.__new__(L2AgentStreamRunner)
    runner.options = SimpleNamespace(baseline='codex', baseline_overrides={},
                                    repo_root=Path(__file__).resolve().parents[1])
    runner.condition = RunCondition(condition)
    runner.work_limits = _work_limits({})
    runner.budget = TokenBudget()
    monkeypatch.setattr('evolink_bench.l2_agent.ProcessBaselineRuntime', lambda manifest, **kwargs: manifest)
    manifest = runner._create_runtime()
    assert manifest.evolution['policy'] == expected
