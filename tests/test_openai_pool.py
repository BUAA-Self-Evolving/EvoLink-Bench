import io
import json

import pytest

from evolink_bench.model import OpenAICompatibleClient, TokenBudget
from evolink_bench.provider_profiles import configure_provider_environment, provider_credentials
from tools.run_new_package_matrix import assign_friday_credentials, job_environment, validate_friday_schedule


def test_pool_is_numeric_and_workers_receive_only_selected_secret():
    env = {"OPENAI_API_KEY_2": "fake-two", "OPENAI_API_KEY_1": "fake-one"}
    pool = provider_credentials("openai", env)
    assert [c.value for c in pool] == ["fake-one", "fake-two"]
    configure_provider_environment("openai", env, credential=pool[1])
    assert env["OPENAI_API_KEY"] == "fake-two"
    assert not any(name.startswith("OPENAI_API_KEY_") for name in env)
    assert "fake-one" not in env.values()
    assert env["TRIEVO_MODEL"] == "gpt-6-luna"
    assert env["TRIEVO_THINKING"] == ""


@pytest.mark.parametrize("env", [{}, {"OPENAI_API_KEY_1": " "},
    {"OPENAI_API_KEY_1": "same", "OPENAI_API_KEY_2": "same"}])
def test_invalid_pool_fails_without_disclosing_values(env):
    with pytest.raises(ValueError):
        provider_credentials("openai", env)


def test_affinity_retains_stream_slot_across_conditions_and_resume():
    pool = provider_credentials("openai", {"OPENAI_API_KEY_1": "fake-one", "OPENAI_API_KEY_2": "fake-two"})
    rows = [{"id": f"{flow}-{condition}", "level": "l2", "flow_id": flow,
             "agent": "codex", "condition": condition, "expected_turns": 3}
            for flow in ("a", "b", "c") for condition in ("reset", "frozen", "evolving")]
    schedule = assign_friday_credentials(rows, pool)
    for flow in ("a", "b", "c"):
        assert len({r["credential_slot"] for r in rows if r["flow_id"] == flow}) == 1
    assert {r["credential_slot"] for r in rows} == {1, 2}
    assert "fake-one" not in json.dumps(schedule)
    validate_friday_schedule({"credential_schedule": schedule}, schedule)
    changed = dict(schedule, slot_names=list(reversed(schedule["slot_names"])))
    with pytest.raises(ValueError):
        validate_friday_schedule({"credential_schedule": schedule}, changed)


@pytest.mark.parametrize("thinking", [None, "disabled", "enabled", "low"])
@pytest.mark.parametrize("base_url", ["https://api.openai.com/v1", "http://127.0.0.1:18766/v1"])
def test_gpt6_official_client_uses_supported_token_parameter(monkeypatch, thinking, base_url):
    if base_url.startswith("http://"):
        monkeypatch.setenv("TRIEVO_PROVIDER_MODE", "openai")
    captured = []
    def request(req, **kwargs):
        captured.append(json.loads(req.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}],
                                     "usage": {"total_tokens": 4}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", request)
    client = OpenAICompatibleClient(base_url=base_url, api_key="fake",
                                    model="gpt-6-luna", budget=TokenBudget(10000), thinking=thinking)
    assert client.complete([{"role": "user", "content": "test"}], max_tokens=64) == "ok"
    assert captured[0]["max_completion_tokens"] == 64
    assert "max_tokens" not in captured[0]
    assert "thinking" not in captured[0]
    if thinking == "disabled":
        assert captured[0]["temperature"] == 0
        assert captured[0]["reasoning_effort"] == "none"
    else:
        assert "temperature" not in captured[0]
        if thinking:
            assert captured[0]["reasoning_effort"] == {"enabled": "medium", "low": "low"}[thinking]
