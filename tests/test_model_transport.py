import http.client
import io
import json

import pytest

from evolink_bench.model import OpenAICompatibleClient, TokenBudget


def client(*, max_retries=2):
    return OpenAICompatibleClient(base_url="https://example.invalid/v1", api_key="test",
                                  model="test", budget=TokenBudget(10000), max_retries=max_retries)


def test_disconnect_retries_same_request_once(monkeypatch):
    calls = []
    def request(value, **kwargs):
        calls.append(value.data)
        if len(calls) == 1:
            raise http.client.RemoteDisconnected("closed")
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}],
                                      "usage": {"total_tokens": 7}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr("time.sleep", lambda _: None)
    model = client()
    assert model.complete([{"role": "user", "content": "judge"}]) == "ok"
    assert len(calls) == 2 and calls[0] == calls[1]
    assert model.budget.used == 7  # Only provider-reported usage is knowable.


def test_repeated_disconnect_is_bounded_and_preserves_type(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(1)
        raise http.client.RemoteDisconnected("closed")
    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr("time.sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="RemoteDisconnected") as error:
        client(max_retries=1).complete([{"role": "user", "content": "judge"}])
    assert len(calls) == 2
    assert isinstance(error.value.__cause__, http.client.RemoteDisconnected)


def test_packycode_terra_judge_uses_responses_and_records_usage(monkeypatch):
    def request(value, **kwargs):
        assert value.full_url == "https://cf.api.fan/v1/responses"
        payload = json.loads(value.data)
        assert payload["input"] == [{"role": "user", "content": "Return JSON."}]
        assert payload["text"] == {"format": {"type": "json_object"}}
        assert payload["reasoning"] == {"effort": "none"}
        assert payload["max_output_tokens"] == 64
        assert "messages" not in payload and "thinking" not in payload
        return io.BytesIO(json.dumps({"object": "response", "status": "completed",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}],
            "usage": {"total_tokens": 19}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", request)
    model = OpenAICompatibleClient(base_url="https://cf.api.fan/v1", api_key="test",
        model="gpt-6.1-terra", budget=TokenBudget(10000), thinking="disabled")
    assert json.loads(model.complete([{"role": "user", "content": "Return JSON."}],
                                    max_tokens=64, json_mode=True)) == {"ok": True}
    assert model.budget.used == 19 and model.budget.calls == 1


def test_incomplete_responses_preserves_usage_without_replaying(monkeypatch):
    calls = []
    def request(value, **kwargs):
        calls.append(value)
        return io.BytesIO(json.dumps({"object": "response", "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {"total_tokens": 20}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", request)
    model = OpenAICompatibleClient(base_url="https://cf.api.fan/v1", api_key="test",
        model="gpt-6.1-terra", budget=TokenBudget(10000))
    with pytest.raises(RuntimeError, match="did not complete"):
        model.complete([{"role": "user", "content": "judge"}])
    assert len(calls) == 1 and model.budget.used == 20
