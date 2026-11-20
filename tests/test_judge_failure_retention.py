import json
import os
from types import SimpleNamespace
from evolink_bench.l2_agent import L2AgentStreamRunner


def test_failed_paid_judge_payload_is_retained_privately_without_scoring(tmp_path):
    runner = object.__new__(L2AgentStreamRunner)
    runner.options = SimpleNamespace(output_root=tmp_path)
    raw = {'raw_attempts': ['{"task_success":null}'], 'status': 'invalid'}
    task = {'stream_id': 's01', 'turn_id': 'turn2'}
    runner._retain_reference_judge_failure(task, 2, raw)
    runner._retain_reference_judge_failure(task, 2, raw)
    files = list((tmp_path / '_judge_failures').glob('*.json'))
    assert len(files) == 2
    for path in files:
        saved = json.loads(path.read_text())
        assert saved['details'] == raw
        assert saved['interaction_index'] == 2
        assert saved['score_committed'] is False
        assert saved['additional_model_calls'] == 0
        if os.name == "posix":
            assert path.stat().st_mode & 0o077 == 0
