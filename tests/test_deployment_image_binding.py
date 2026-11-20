from pathlib import Path
from unittest.mock import patch

import pytest

from evolink_bench.baselines.deployment import docker_run_image, validate_image_binding
from evolink_bench.baselines.base import FlowContext
from evolink_bench.baselines.manifest import load_manifest
from evolink_bench.baselines.process import BaselineProtocolError, ProcessBaselineRuntime
from evolink_bench.model import TokenBudget


def test_image_in_environment_or_entrypoint_is_not_image_binding():
    for command in (
        ["docker", "run", "-e", "patched:1", "old:1"],
        ["docker", "run", "--entrypoint=patched:1", "old:1"],
        ["docker", "run", "old:1", "patched:1"],
    ):
        with pytest.raises(ValueError, match="differs"):
            validate_image_binding(command, "patched:1")


def test_supported_launch_options_and_command_arguments():
    cmd = ["docker", "run", "--rm", "-i", "--memory", "8g", "--name=x",
           "-v", "/host:/workspace", "--cap-drop", "ALL", "--", "patched:1", "python", "-u"]
    assert docker_run_image(cmd) == "patched:1"
    validate_image_binding(cmd, "patched:1")
    validate_image_binding(["python", "bridge.py"], "unused:1")


@pytest.mark.parametrize("cmd", [["docker", "run", "--new-flag", "value", "image"],
                                ["docker", "run", "--env"], ["docker", "run"]])
def test_ambiguous_or_missing_image_fails_closed(cmd):
    with pytest.raises(ValueError):
        docker_run_image(cmd)


def test_hardcoded_old_image_stops_before_state_or_process_creation(tmp_path):
    root = Path(__file__).parents[1]
    manifest = load_manifest(root / "baseline/manifests/adaptive-auto-harness.json")
    command = ["old:1" if x == "{image}" else x for x in manifest.adapter["command"]]
    manifest = manifest.with_overrides({"adapter": {"command": command}, "options": {"image": "patched:1"}})
    runtime = ProcessBaselineRuntime(manifest, budget=TokenBudget(100), repo_root=root)
    with patch("evolink_bench.baselines.process.NdjsonProcess") as spawn, \
         patch.object(runtime, "_verify_source_revision") as verify:
        with pytest.raises(BaselineProtocolError, match="differs"):
            runtime.start_flow(FlowContext("flow", tmp_path, tmp_path))
    spawn.assert_not_called()
    verify.assert_not_called()
    assert runtime._state_dir is None
