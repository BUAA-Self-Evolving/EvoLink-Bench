"""Validate the image actually selected by Docker before starting an adapter."""
from __future__ import annotations

from ..docker_proxy import is_docker_command


# Unknown options fail closed: guessing whether an argument is a flag value
# could mistake an environment value or a mount source for the executable image.
_FLAGS = {
    "--rm", "--init", "--privileged", "--read-only", "--sig-proxy",
    "--detach", "--interactive", "--tty", "--publish-all", "--disable-content-trust",
    "-d", "-i", "-t", "-it", "-ti", "-P",
}
_VALUES = {
    "--name", "--user", "--workdir", "--env", "--env-file", "--volume", "--mount",
    "--memory", "--memory-swap", "--memory-reservation", "--cpus", "--cpu-shares",
    "--cpuset-cpus", "--cpuset-mems", "--pids-limit", "--cap-add", "--cap-drop",
    "--security-opt", "--network", "--net", "--entrypoint", "--hostname", "--label",
    "--label-file", "--add-host", "--dns", "--device", "--gpus", "--ipc", "--pid",
    "--shm-size", "--ulimit", "--tmpfs", "--publish", "--pull", "--platform",
    "--restart", "--log-driver", "--log-opt", "--stop-timeout", "--stop-signal",
    "-u", "-w", "-e", "-v", "-p", "-h", "-l", "-m",
}


def docker_run_image(command: list[str]) -> str | None:
    """Read Docker's IMAGE positional argument, never searching arbitrary argv."""
    if not is_docker_command(command):
        return None
    if len(command) < 2 or command[1] != "run":
        raise ValueError("adapter Docker command must use an explicit docker run")
    index = 2
    while index < len(command):
        token = command[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            break
        flag, equals, _ = token.partition("=")
        if flag in _FLAGS:
            index += 1
        elif flag in _VALUES:
            index += 1 if equals else 2
        else:
            raise ValueError(f"unsupported Docker launch option: {flag}")
    if index >= len(command) or not command[index] or command[index].startswith("-"):
        raise ValueError("adapter Docker command is missing its image")
    return command[index]


def validate_image_binding(command: list[str], expected: object, *, allow_template: bool = False) -> None:
    """Reject silent options.image/actual argv divergence without launching work."""
    actual = docker_run_image(command)
    if actual is None or expected is None:
        return
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError("options.image must be a non-empty image reference")
    if actual != expected and not (allow_template and actual == "{image}"):
        raise ValueError("adapter Docker image differs from options.image; use {image} in the image position")
