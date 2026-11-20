import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from evolink_bench.verifier_workspace import WORKSPACE_GUARD, bind_workspace_user, workspace_input_manifest


BINDINGS = [{"name": "submission", "source": "workspace", "path": "agent_workspace/output"}]


def invoke_guard(tmp_path, manifest, request=None):
    verifier = tmp_path.parent / (tmp_path.name + "_fake_verifier.py")
    verifier.write_text(
        "import json,sys\n"
        "r=json.load(sys.stdin)\n"
        "assert sys.argv == [__file__]\n"
        "print(json.dumps({'fake_verifier_called':True,'request':r}))\n", encoding="utf-8")
    envelope = {"workspace_manifest": manifest, "verifier_id": "test", "request": request or {"bindings": {}}}
    return subprocess.run([sys.executable, "-c", WORKSPACE_GUARD, str(verifier)],
                          input=json.dumps(envelope), text=True, capture_output=True,
                          env={**os.environ, "L2_VERIFIER_WORKSPACE": str(tmp_path)}, timeout=15)


def test_guard_preserves_request_and_runs_verifier(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output/index.html").write_text("unchanged", encoding="utf-8")
    manifest = workspace_input_manifest(tmp_path, BINDINGS)
    request = {"bindings": {"submission": {"kind": "path", "path": "agent_workspace/output"}}}
    result = invoke_guard(tmp_path, manifest, request)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"fake_verifier_called": True, "request": request}
    assert "TRIEVO_WORKSPACE_GUARD" in result.stderr
    assert (tmp_path / "output/index.html").read_text() == "unchanged"


@pytest.mark.parametrize("change", ["missing", "different"])
def test_guard_blocks_stale_or_missing_mounted_file_before_verifier(tmp_path, change):
    (tmp_path / "output").mkdir()
    p = tmp_path / "output/index.html"
    p.write_text("original", encoding="utf-8")
    manifest = workspace_input_manifest(tmp_path, BINDINGS)
    if change == "missing":
        p.unlink()
    else:
        p.write_text("changed", encoding="utf-8")
    result = invoke_guard(tmp_path, manifest)
    output = json.loads(result.stdout)
    assert result.returncode == 0
    assert output["status"] == "error" and output["score"] is None
    assert output["private_diagnostics"]["reason"] == "workspace_input_visibility_error"
    assert "fake_verifier_called" not in result.stdout


def test_missing_agent_submission_is_not_infrastructure_failure(tmp_path):
    manifest = workspace_input_manifest(tmp_path, BINDINGS)
    assert manifest == [{"path": ".", "kind": "directory", "children": []}, {"path": "output", "kind": "absent"}]
    assert json.loads(invoke_guard(tmp_path, manifest).stdout)["fake_verifier_called"]


def test_guard_blocks_foreign_output_absent_from_host_snapshot(tmp_path):
    manifest = workspace_input_manifest(tmp_path, BINDINGS)
    (tmp_path / "output").mkdir()
    result = json.loads(invoke_guard(tmp_path, manifest).stdout)
    assert result["status"] == "error" and result["score"] is None


@pytest.mark.parametrize("relative", ["/workspace/output", "agent_workspace/../secret"])
def test_binding_escape_rejected(tmp_path, relative):
    with pytest.raises(ValueError):
        workspace_input_manifest(tmp_path, [{"source": "workspace", "path": relative}])


@pytest.mark.skipif(os.name != "posix", reason="POSIX container identity")
def test_identity_matches_owner_without_chmod(tmp_path):
    tmp_path.chmod(0o700)
    before = tmp_path.stat()
    assert bind_workspace_user(tmp_path) == f"{before.st_uid}:{before.st_gid}"
    assert tmp_path.stat().st_mode == before.st_mode


@pytest.mark.skipif(os.name != "posix", reason="POSIX workspace permissions")
def test_real_checkpoint_restore_keeps_private_root_but_verifier_uses_owner(tmp_path):
    import shutil
    import tempfile
    from evolink_bench.l2_agent import _archive_tree, _restore_tree_archive

    seed = tmp_path / "seed"
    seed.mkdir(mode=0o775)
    seed.chmod(0o775)
    (seed / "output").mkdir()
    (seed / "output/index.html").write_text("saved artifact", encoding="utf-8")
    fresh = tmp_path / "fresh"
    shutil.copytree(seed, fresh)
    archive = tmp_path / "workspace.zip"
    _archive_tree(fresh, archive)
    with tempfile.TemporaryDirectory(dir=tmp_path) as name:
        restored = type(tmp_path)(name)
        _restore_tree_archive(archive, restored)
        assert fresh.stat().st_mode & 0o777 == 0o775
        assert restored.stat().st_mode & 0o777 == 0o700
        assert (restored / "output/index.html").read_bytes() == (fresh / "output/index.html").read_bytes()
        assert bind_workspace_user(restored) == f"{os.getuid()}:{os.getgid()}"


def test_runtime_selects_owner_and_guards_input_before_native(tmp_path, monkeypatch):
    import evolink_bench.l2_agent as module
    from evolink_bench.baselines.base import BaselineReply

    package = tmp_path / "package"
    turn = package / "turn1"
    turn.mkdir(parents=True)
    (turn / "verifier.py").write_text("# fixture", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "output").mkdir()
    (workspace / "output/index.html").write_text("artifact", encoding="utf-8")
    runner = object.__new__(module.L2AgentStreamRunner)
    runner.options = SimpleNamespace(package_dir=package, browser_verifier_image="browser", verifier_image="plain")
    task = {"evaluation": {"submission_contract": {"source_binding": "submission"},
                           "native_verifier": {"entrypoint": "verifier.py", "input_bindings": BINDINGS,
                                               "verifier_id": "test"}}}
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        result = {"schema_version": "l2_native_verifier_result/1.0", "verifier_id": "test",
                  "status": "error", "score": None, "error": "guard denied",
                  "public_summary": {"observable_deficiencies": []},
                  "private_diagnostics": {"reason": "workspace_input_visibility_error"}}
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "bind_workspace_user", lambda _: "1001:1001")
    result = runner._verify_taskstream_in_volume(task=task, turn_dir=turn, workspace=workspace,
                                               reply=BaselineReply(text="answer"))
    command, options = calls[0]
    assert command[command.index("--user") + 1] == "1001:1001"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--network") + 1] == "none"
    assert WORKSPACE_GUARD in command
    assert json.loads(options["input"])["workspace_manifest"]
    assert result["category"] == "error" and result["score"] is None
    assert result["verification_transport"]["user"] == "1001:1001"
