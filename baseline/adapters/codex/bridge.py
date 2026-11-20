from __future__ import annotations

import json
import hashlib
from collections import Counter
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


PROTOCOL_VERSION = "1.0"
USAGE_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cached_input_tokens": "cached_read_tokens",
    "cache_write_input_tokens": "cached_write_tokens",
    "reasoning_output_tokens": "reasoning_tokens",
}


class CodexError(RuntimeError):
    pass


class CodexBridge:
    """Map Codex exec JSONL onto the Flow/Turn/Interaction lifecycle."""

    def __init__(self, run_command: Callable[..., Any] | None = None) -> None:
        self.options: dict[str, Any] = {}
        self.evolution: dict[str, Any] = {}
        self.workspace: Path | None = None
        self.state_dir: Path | None = None
        self.turn_id: str | None = None
        self.session_id: str | None = None
        self._usage: dict[str, int] = {}
        self._evolved = True
        self._run_command = run_command or subprocess.run

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported baseline runtime protocol")
        if params.get("baseline_id") != "codex":
            raise ValueError("unexpected baseline id")
        self.options = dict(params.get("options", {}))
        self.evolution = dict(params.get("evolution", {}))
        if self.evolution.get("policy", "disabled") not in {"disabled", "turn_boundary"}:
            raise ValueError("Codex evolution.policy must be disabled or turn_boundary")
        return {
            "protocol_version": PROTOCOL_VERSION,
            "framework": "codex",
            "integration": "exec_jsonl",
            "session_policy": "fresh_per_turn",
            "api_calls_semantics": "exec_invocations_lower_bound",
        }

    def start_flow(self, params: dict[str, Any]) -> dict[str, Any]:
        self.workspace = Path(str(params["workspace"])).resolve()
        self.state_dir = Path(str(params["state_dir"])).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "home").mkdir(exist_ok=True)
        (self.state_dir / "learning").mkdir(exist_ok=True)
        self.session_id = None
        self.turn_id = None
        self._evolved = True
        return {"flow_id": str(params.get("flow_id", "")), "session_policy": "fresh_per_turn"}

    def start_turn(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_flow()
        if not self._evolved:
            raise RuntimeError("previous turn has not crossed the evolution barrier")
        scratch = self.state_dir / "sessions"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir()
        self.turn_id = str(params["turn_id"])
        self.session_id = None
        self._usage = {}
        self._evolved = False
        return {"turn_id": self.turn_id, "fresh_session": True}

    def interact(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_turn(params)
        if self._evolved:
            raise RuntimeError("turn already crossed the evolution barrier")
        if int(params.get("remaining_token_budget", 1)) <= 0:
            raise CodexError("Codex interaction token budget is exhausted")
        prompt = str(params.get("request", ""))
        if not self.session_id:
            prompt = (
                "Complete the user task in the shared workspace. Do not access evaluator or "
                "baseline state directories or modify persistent learning state.\n"
                + "Flow memory (read-only):\n" + self._memory() + "\n\n" + prompt
            )
            if params.get("history"):
                prompt += "\nPublic conversation:\n" + json.dumps(params["history"], ensure_ascii=True)
        parsed = self._execute(prompt, evolution=False)
        received = parsed["session_id"]
        if self.session_id is not None and received != self.session_id:
            raise CodexError("Codex changed session within a Turn")
        self.session_id = received
        usage = _usage_delta(self._usage, parsed["usage"])
        self._usage = parsed["usage"]
        return {
            "text": parsed["text"],
            "actions": [],
            "tool_calls": parsed["tool_calls"],
            "events": parsed["events"],
            "usage": usage,
            "actions_are_executed": True,
            "tool_calls_are_executed": True,
            "raw": {"session_id": self.session_id},
        }

    def evolve(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_turn(params)
        if self._evolved:
            raise RuntimeError("turn already crossed the evolution barrier")
        if not params.get("update_enabled", True) or self.evolution.get("policy", "disabled") == "disabled":
            self._evolved = True
            return {
                "completed": True,
                "events": [{"type": "evolution.skipped", "reason": params.get("skip_reason") or "policy_disabled"}],
                "usage": {},
            }
        prompt = (
            "Review only the public trajectory and feedback below. Return a JSON object with "
            "a memory string containing concise reusable lessons, preserving useful existing lessons. "
            "Do not use tools, inspect files, infer hidden answers, or solve another task.\n"
            + "Existing memory:\n" + self._memory() + "\nPublic evidence:\n"
            + _encode_public_evolution_context(
                _public_evolution_context(params),
                lossless_dedup=bool(self.options.get("lossless_evolution_context_dedup", False)),
                lossless_line_dedup=bool(self.options.get("lossless_evolution_line_dedup", False)),
            )
        )
        if self.options.get("lossless_evolution_context_dedup") and len(prompt) > 1_000_000:
            raise CodexError("lossless evolution input still exceeds the local transport bound; no model dispatched")
        parsed = self._execute(prompt, evolution=True)
        usage = _usage_delta({}, parsed["usage"])
        self._evolved = True
        try:
            learned = json.loads(parsed["text"])
            memory = learned["memory"]
            if not isinstance(memory, str) or len(memory) > int(self.options.get("memory_max_chars", 12000)):
                raise ValueError("memory must be a bounded string")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return {
                "completed": False,
                "events": [{"type": "evolution.failed", "message": str(exc)}],
                "usage": usage,
            }
        target = self.state_dir / "learning" / "memory.md"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(memory, encoding="utf-8")
        temporary.replace(target)
        return {"completed": True, "events": [{"type": "evolution.completed"}], "usage": usage}

    def end_flow(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.turn_id = None
        self.session_id = None
        return {"completed": True}

    def _require_flow(self) -> None:
        if self.workspace is None or self.state_dir is None:
            raise RuntimeError("flow has not started")

    def _require_turn(self, params: dict[str, Any]) -> None:
        self._require_flow()
        if self.turn_id is None or str(params.get("turn_id")) != self.turn_id:
            raise RuntimeError("request belongs to an inactive turn")

    def _memory(self) -> str:
        target = self.state_dir / "learning" / "memory.md"
        return target.read_text(encoding="utf-8") if target.exists() else ""

    def _environment(self, codex_home: Path) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(self.state_dir / "home")
        env["CODEX_HOME"] = str(codex_home)
        key_env = str(self.options.get("api_key_env", "TRIEVO_API_KEY"))
        key = env.get(key_env) or env.get("CODEX_API_KEY") or env.get("OPENAI_API_KEY")
        if key:
            env["TRIEVO_CODEX_API_KEY"] = key
            env["CODEX_API_KEY"] = key
        return env

    def _execute(self, prompt: str, *, evolution: bool) -> dict[str, Any]:
        codex_home = self.state_dir / ("evolution-home" if evolution else "sessions")
        if evolution and codex_home.exists():
            shutil.rmtree(codex_home)
        codex_home.mkdir(exist_ok=True)
        config = self._config(evolution=evolution)
        (codex_home / "config.toml").write_text(config, encoding="utf-8")
        executable = self.options.get("executable", "codex")
        command = list(executable) if isinstance(executable, list) else [str(executable)]
        command.extend(["exec", "--json", "--skip-git-repo-check"])
        if evolution:
            command.extend(["--ephemeral", "--sandbox", "read-only"])
            schema = codex_home / "memory.schema.json"
            schema.write_text(json.dumps({
                "type": "object", "properties": {"memory": {"type": "string"}},
                "required": ["memory"], "additionalProperties": False,
            }), encoding="utf-8")
            command.extend(["--output-schema", str(schema)])
            cwd = codex_home / "workspace"
            cwd.mkdir(exist_ok=True)
        else:
            command.extend(["--sandbox", "danger-full-access"])
            cwd = self.workspace
        if self.session_id and not evolution:
            command.extend(["resume", self.session_id])
        command.append("-")
        timeout = float(
            self.evolution.get("timeout_seconds", 900) if evolution
            else self.options.get("request_timeout_seconds", 1700)
        )
        try:
            completed = self._run_command(
                command, input=prompt, cwd=str(cwd), env=self._environment(codex_home),
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            def decode(value):
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            evidence = {"returncode": 124, "timeout_seconds": timeout,
                        "stdout": decode(exc.stdout), "stderr": decode(exc.stderr),
                        "unknown_usage_retained": True, "automatic_retry": False}
            key = self._environment(codex_home).get("TRIEVO_CODEX_API_KEY", "")
            if key:
                evidence["stdout"] = evidence["stdout"].replace(key, "[redacted]")
                evidence["stderr"] = evidence["stderr"].replace(key, "[redacted]")
            encoded = json.dumps(evidence, ensure_ascii=True)
            # The selected learning-state export need not include codex_home.
            # Mirror failure-only evidence into the archived failed workspace.
            for directory in (codex_home, self.workspace / ".evolink-native-diagnostics"):
                try:
                    if directory.is_symlink():
                        raise OSError("diagnostic directory is a symlink")
                    directory.mkdir(exist_ok=True)
                    target = directory / "native-timeout-evidence.json"
                    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
                    if target.is_symlink():
                        raise OSError("diagnostic file is a symlink")
                    descriptor = os.open(target, flags, 0o600)
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        stream.write(encoded)
                    target.chmod(0o600)
                except OSError as capture_error:
                    print(json.dumps({"codex_timeout_evidence_capture_error": type(capture_error).__name__}),
                          file=sys.stderr, flush=True)
            raise CodexError("Codex request timed out; native output retained; do not replay executed side effects automatically") from exc
        try:
            parsed = _parse_output(completed.stdout)
        except CodexError as exc:
            self._log_native_failure(completed, codex_home)
            if completed.returncode != 0:
                detail = completed.stderr.strip()[-2000:]
                key = self._environment(codex_home).get("TRIEVO_CODEX_API_KEY")
                if key:
                    detail = detail.replace(key, "[redacted]")
                raise CodexError(f"Codex exited with code {completed.returncode}: {detail}") from exc
            raise
        if completed.returncode != 0:
            self._log_native_failure(completed, codex_home)
            raise CodexError(parsed["error"] or f"Codex exited with code {completed.returncode}")
        if parsed["error"]:
            self._log_native_failure(completed, codex_home)
            raise CodexError(parsed["error"])
        return parsed

    def _log_native_failure(self, completed: Any, codex_home: Path) -> None:
        key = self._environment(codex_home).get("TRIEVO_CODEX_API_KEY", "")
        detail = {"returncode": completed.returncode,
                  "stdout": completed.stdout, "stderr": completed.stderr}
        encoded = json.dumps({"codex_native_failure": detail}, ensure_ascii=True)
        if key:
            encoded = encoded.replace(key, "[redacted]")
        print(encoded, file=sys.stderr, flush=True)

    def _config(self, *, evolution: bool) -> str:
        model = str(self.options.get("model") or os.getenv("TRIEVO_MODEL") or "")
        if not model:
            raise ValueError("options.model or TRIEVO_MODEL is required")
        base_url = str(
            self.options.get("base_url") or os.getenv("TRIEVO_BASE_URL")
            or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        )
        values: dict[str, Any] = {
            "model": model,
            "model_provider": "trievo",
            "approval_policy": "never",
            "model_reasoning_effort": str(self.options.get("reasoning_effort", "medium")),
            "web_search": "disabled" if evolution else str(self.options.get("web_search", "disabled")),
            "memories.generate_memories": False,
            "memories.use_memories": False,
            "features.memories": False,
            "features.multi_agent": False,
            "features.multi_agent_v2": False,
            "features.shell_tool": not evolution,
        }
        for name in ("model_context_window", "model_auto_compact_token_limit"):
            if self.options.get(name) is not None:
                values[name] = int(self.options[name])
        settings = "\n".join(f"{name} = {json.dumps(value)}" for name, value in values.items())
        return (
            settings + "\n[model_providers.trievo]\nname = \"EvoLink-Bench\"\n"
            + f"base_url = {json.dumps(base_url)}\n"
            + "env_key = \"TRIEVO_CODEX_API_KEY\"\nwire_api = \"responses\"\n"
            + f"request_max_retries = {int(self.options.get('request_max_retries', 2))}\n"
        )


def _usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    usage = {
        target: max(0, after.get(source, 0) - before.get(source, 0))
        for source, target in USAGE_FIELDS.items()
    }
    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    usage["api_calls"] = 1
    return usage


def _parse_output(output: str) -> dict[str, Any]:
    session_id = None
    text = ""
    usage = None
    error = None
    terminal_failure = None
    events = []
    calls = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexError("Codex emitted non-JSON output") from exc
        if not isinstance(event, dict):
            raise CodexError("Codex event must be an object")
        kind = event.get("type")
        events.append(event)
        if kind == "thread.started":
            session_id = event.get("thread_id")
        elif kind == "turn.completed":
            raw = event.get("usage")
            if not isinstance(raw, dict):
                raise CodexError("Codex completion is missing usage")
            try:
                usage = {name: int(raw.get(name, 0)) for name in USAGE_FIELDS}
            except (TypeError, ValueError) as exc:
                raise CodexError("Codex usage must contain integers") from exc
            if any(value < 0 for value in usage.values()):
                raise CodexError("Codex usage must be non-negative")
            # Native Codex emits reconnect notifications as `error` events.
            # A completed turn supersedes those progress notices, while an
            # explicit terminal failure must never become a successful reply.
            if terminal_failure is None:
                error = None
        elif kind in {"error", "turn.failed"}:
            detail = event.get("error", event)
            message = str(detail.get("message", "Codex failed")) if isinstance(detail, dict) else str(detail)
            if kind == "turn.failed":
                terminal_failure = message
            error = terminal_failure or message
        elif kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                raise CodexError("Codex item must be an object")
            item_type = item.get("type")
            if item_type == "agent_message":
                text = str(item.get("text", ""))
            elif item_type in {"command_execution", "file_change", "mcp_tool_call", "web_search", "collab_tool_call"}:
                calls.append({"tool": item_type, "arguments": item, "result": item.get("aggregated_output", item.get("result"))})
    if not error and (not isinstance(session_id, str) or not session_id or usage is None):
        raise CodexError("Codex output is missing a session or completed turn")
    return {"session_id": session_id, "text": text, "usage": usage or {}, "error": error, "events": events, "tool_calls": calls}


def _encode_public_evolution_context(context: dict[str, Any], *, lossless_dedup: bool,
                                     lossless_line_dedup: bool = False) -> str:
    """Intern repeated long public strings without dropping any evidence bytes."""
    original = json.dumps(context, ensure_ascii=True)
    if not lossless_dedup or len(original) < 950_000:
        return original
    counts: Counter[str] = Counter()
    tag = "$trievo_public_string_ref"
    def count(value: Any) -> None:
        if isinstance(value, str) and len(value) >= 512:
            counts[value] += 1
        elif isinstance(value, list):
            for item in value: count(item)
        elif isinstance(value, dict):
            if tag in value:
                raise CodexError("reserved lossless evidence reference collision; no model dispatched")
            for item in value.values(): count(item)
    count(context)
    table: dict[str, str] = {}
    def encode(value: Any) -> Any:
        if isinstance(value, str) and counts.get(value, 0) > 1:
            key = hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()
            if key in table and table[key] != value:
                raise CodexError("public evidence digest collision")
            table[key] = value
            return {tag: key}
        if isinstance(value, list): return [encode(x) for x in value]
        if isinstance(value, dict): return {k: encode(v) for k, v in value.items()}
        return value
    encoded = encode(context)
    def decode(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {tag}: return table[value[tag]]
        if isinstance(value, list): return [decode(x) for x in value]
        if isinstance(value, dict): return {k: decode(v) for k, v in value.items()}
        return value
    if decode(encoded) != context:
        raise CodexError("lossless public evidence round-trip mismatch")
    packed = json.dumps({"encoding": "lossless_public_string_interning_v1",
        "instructions": "The data is the complete original public evidence. Resolve each $trievo_public_string_ref using strings; no evidence is omitted. Do not use tools.",
        "strings": table, "data": encoded}, ensure_ascii=True)
    best = packed if len(packed) < len(original) else original
    if lossless_line_dedup and len(best) >= 950_000:
        candidate = _encode_public_lines(context)
        if len(candidate) < len(best):
            best = candidate
    return best


def _encode_public_lines(context: dict[str, Any]) -> str:
    """Readable, reversible line interning; never truncates public evidence."""
    ref, parts = '$trievo_public_line_ref', '$trievo_public_string_parts'
    counts: Counter[str] = Counter()
    def count(value: Any) -> None:
        if isinstance(value, str):
            counts.update(line for line in value.splitlines(keepends=True) if len(line) >= 8)
        elif isinstance(value, list):
            for item in value: count(item)
        elif isinstance(value, dict):
            if ref in value or parts in value:
                raise CodexError('reserved lossless line reference collision; no model dispatched')
            for item in value.values(): count(item)
    count(context)
    table: list[str] = []
    keys: dict[str, int] = {}
    def encode(value: Any) -> Any:
        if isinstance(value, str):
            segments: list[Any] = []
            literal: list[str] = []
            for line in value.splitlines(keepends=True):
                if counts.get(line, 0) > 1:
                    if literal: segments.append(''.join(literal)); literal = []
                    if line not in keys:
                        keys[line] = len(table)
                        table.append(line)
                    segments.append(keys[line])
                else: literal.append(line)
            if literal: segments.append(''.join(literal))
            return {parts: segments} if any(type(x) is int for x in segments) else value
        if isinstance(value, list): return [encode(x) for x in value]
        if isinstance(value, dict): return {k: encode(v) for k, v in value.items()}
        return value
    encoded = encode(context)
    def decode(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {parts}:
            return ''.join(table[x] if type(x) is int else x for x in value[parts])
        if isinstance(value, list): return [decode(x) for x in value]
        if isinstance(value, dict): return {k: decode(v) for k, v in value.items()}
        return value
    if decode(encoded) != context:
        raise CodexError('lossless public line round-trip mismatch')
    return json.dumps({'encoding': 'lossless_public_line_interning_v1',
        'instructions': 'This is complete public evidence. Reconstruct each $trievo_public_string_parts by concatenating its literal strings and lines referenced by zero-based integer indices into the lines array. Line endings are preserved. No evidence is omitted. Do not use tools.',
        'lines': table, 'data': encoded}, ensure_ascii=True, separators=(',', ':'))


def _public_evolution_context(params: dict[str, Any]) -> dict[str, Any]:
    trajectory_keys = {"index", "interaction_index", "request", "response", "actions", "tool_calls", "events", "score", "passed"}
    feedback_keys = {"interaction_index", "feedback", "score", "passed"}
    return {
        "turn_id": params.get("turn_id"),
        "trajectory": [{key: value for key, value in row.items() if key in trajectory_keys}
                       for row in params.get("trajectory", []) if isinstance(row, dict)],
        "feedback": [{key: value for key, value in row.items() if key in feedback_keys}
                     for row in params.get("feedback", []) if isinstance(row, dict)],
    }


def main() -> int:
    bridge = CodexBridge()
    methods = {name: getattr(bridge, name) for name in (
        "initialize", "start_flow", "start_turn", "interact", "evolve", "end_flow",
    )}
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("baseline request must be an object")
            method = request["method"]
            result = methods[method](request.get("params", {}))
            response = {"id": request.get("id"), "result": result}
        except Exception as exc:
            request_id = request.get("id") if isinstance(request, dict) else None
            response = {"id": request_id, "error": {"message": f"{type(exc).__name__}: {exc}"}}
        print(json.dumps(response, ensure_ascii=True), flush=True)
        if isinstance(request, dict) and request.get("method") == "end_flow":
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
