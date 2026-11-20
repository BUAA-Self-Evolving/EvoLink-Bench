import json
import os
import subprocess

import pytest

from test_codex_baseline import make_bridge
from baseline.adapters.codex.bridge import CodexError


def test_native_timeout_evidence_is_archivable_redacted_and_never_retried(tmp_path, monkeypatch):
    secret = "offline-secret-do-not-print"
    monkeypatch.setenv("TRIEVO_API_KEY", secret)
    calls = []
    def timeout(*args, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired("offline", 1, output=('partial ' + secret).encode(),
                                        stderr=('diagnostic ' + secret).encode())
    bridge = make_bridge(tmp_path, run_command=timeout)
    with pytest.raises(CodexError, match="do not replay"):
        bridge.interact({"turn_id": "t1", "request": "offline"})
    assert len(calls) == 1
    evidence_path = bridge.workspace / ".evolink-native-diagnostics/native-timeout-evidence.json"
    encoded = evidence_path.read_text()
    evidence = json.loads(encoded)
    assert secret not in encoded and "[redacted]" in encoded
    assert evidence["stdout"].startswith("partial ")
    assert evidence["unknown_usage_retained"] is True and evidence["automatic_retry"] is False
    if os.name == "posix":
        assert evidence_path.stat().st_mode & 0o077 == 0
