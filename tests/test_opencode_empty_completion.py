import json
import subprocess

import pytest

from baseline.adapters.opencode.bridge import OpenCodeBridge, OpenCodeError, _parse_output


@pytest.mark.parametrize("output", ["", '{"sessionID":"previous","type":"step_start"}',
    '{"type":"text","part":{"text":"unbound"}}'])
def test_empty_or_unbound_output_is_not_a_completed_reply(tmp_path, output):
    bridge = OpenCodeBridge(run_command=lambda *a, **k: subprocess.CompletedProcess([], 0, output, ""))
    bridge.initialize({"protocol_version": "1.0", "options": {"model": "offline/mock"}})
    workspace, state = tmp_path / "workspace", tmp_path / "state"
    workspace.mkdir()
    state.mkdir()
    bridge.start_flow({"workspace": str(workspace), "state_dir": str(state)})
    bridge.start_turn({"turn_id": "t1"})
    bridge.session_id = "previous"
    with pytest.raises(OpenCodeError, match="no session-bound"):
        bridge.interact({"turn_id": "t1", "request": "offline test"})


def test_missing_usage_is_unknown_instead_of_zero_cash():
    output = json.dumps({"sessionID": "s", "type": "text", "part": {"text": "saved reply"}})
    result = _parse_output(output)
    assert result["usage_status"] == "unknown"
    assert result["usage"]["estimated_cost_usd"] is None
    assert result["text"] == "saved reply"
