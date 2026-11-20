import json

import pytest

from tools.packy_responses_gateway import responses_request, chat_result, chat_sse, read_responses_stream, UpstreamStreamError


def test_tool_conversation_and_schema_preserve_identity():
    payload = responses_request({"model": "gpt-6.1-terra", "max_tokens": 1200,
        "messages": [{"role": "system", "content": "Use tools."},
                     {"role": "user", "content": "Inspect."},
                     {"role": "assistant", "content": None, "tool_calls": [{
                         "id": "call_x", "type": "function", "function": {
                             "name": "terminal", "arguments": '{"cmd":"pwd"}'}}]},
                     {"role": "tool", "tool_call_id": "call_x", "content": "/workspace"}],
        "tools": [{"type": "function", "function": {"name": "terminal", "parameters": {
            "type": "object", "properties": {"cmd": {"type": "string"}}}}}],
        "tool_choice": {"type": "function", "function": {"name": "terminal"}}})
    assert payload["input"][-2] == {"type": "function_call", "call_id": "call_x",
        "name": "terminal", "arguments": '{"cmd":"pwd"}'}
    assert payload["input"][-1]["output"] == "/workspace"
    assert payload["tools"][0]["parameters"]["properties"]["cmd"]["type"] == "string"
    assert payload["tool_choice"] == {"type": "function", "name": "terminal"}
    assert payload["max_output_tokens"] == 1200
    assert payload["instructions"] == "Use tools."


def test_image_and_json_format_are_preserved():
    payload = responses_request({"model": "gpt-6.1-terra", "messages": [{"role": "user",
        "content": [{"type": "text", "text": "Read image."}, {"type": "image_url",
        "image_url": {"url": "data:image/png;base64,abc", "detail": "high"}}]}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "answer", "strict": True, "schema": {"type": "object"}}}})
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    assert payload["text"]["format"]["strict"] is True


def test_terra_temperature_is_omitted_for_provider_compatibility():
    payload = responses_request({'model': 'gpt-6.1-terra', 'messages': [],
                                 'temperature': 0, 'reasoning_effort': 'none'})
    assert 'temperature' not in payload


@pytest.mark.parametrize('code,status', [('rate_limit_exceeded', 429), ('server_error', 502),
    ('context_length_exceeded', 400), ('insufficient_quota', 402)])
def test_provider_stream_error_keeps_retry_and_billing_category(code, status):
    import io
    body = ('data: ' + json.dumps({'type': 'error', 'code': code, 'message': 'provider failure'}) + '\n\n').encode()
    with pytest.raises(UpstreamStreamError) as error:
        read_responses_stream(io.BytesIO(body))
    assert error.value.status == status
    assert error.value.category == code


def test_tool_result_stream_and_cache_usage():
    result = chat_result({"id": "resp1", "model": "gpt-6.1-terra", "status": "completed",
        "output": [{"type": "reasoning", "summary": []}, {"type": "function_call",
        "call_id": "call_a", "name": "terminal", "arguments": "{}"}],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                  "input_tokens_details": {"cached_tokens": 80}}})
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["usage"]["prompt_tokens_details"]["cached_tokens"] == 80
    events = [json.loads(line[6:]) for line in chat_sse(result).decode().splitlines()
              if line.startswith("data: {")]
    assert events[0]["choices"][0]["delta"]["tool_calls"][0]["id"] == "call_a"
    assert events[-1]["usage"]["total_tokens"] == 120


def test_incomplete_is_length_not_successful_stop():
    result = chat_result({"status": "incomplete", "output": [{"type": "message",
        "content": [{"type": "output_text", "text": "partial"}]}]})
    assert result["choices"][0]["finish_reason"] == "length"
    with pytest.raises(ValueError):
        chat_result({"status": "failed"})
    with pytest.raises(ValueError):
        responses_request({"model": "other", "messages": []})


def test_completed_event_without_output_preserves_tool_receipt():
    import io
    events = [{"type": "response.output_item.done", "output_index": 0,
        "item": {"type": "function_call", "call_id": "call1", "name": "echo", "arguments": "{}"}},
        {"type": "response.completed", "response": {"status": "completed", "output": [],
            "usage": {"total_tokens": 100}}}]
    stream = io.BytesIO("".join('data: ' + json.dumps(event) + '\n\n' for event in events).encode())
    result = chat_result(read_responses_stream(stream))
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == "call1"
    assert result["usage"]["total_tokens"] == 100
    with pytest.raises(ValueError, match="ended before completion"):
        read_responses_stream(io.BytesIO(b'data: {"type":"response.created"}\n\n'))


def test_disconnected_queued_client_never_dispatches():
    import socket, threading
    from tools.packy_responses_gateway import upstream_slot
    connection, client = socket.socketpair()
    lock = threading.BoundedSemaphore(1)
    client.close()
    try:
        with pytest.raises(UpstreamStreamError) as error:
            with upstream_slot(lock, connection):
                pytest.fail('disconnected request dispatched')
        assert error.value.status == 499
        assert lock.acquire(blocking=False)
    finally:
        connection.close()


def test_expired_queue_never_consumes_upstream_slot():
    import socket, threading
    from tools.packy_responses_gateway import upstream_slot
    connection, client = socket.socketpair()
    lock = threading.BoundedSemaphore(1)
    lock.acquire()
    try:
        with pytest.raises(UpstreamStreamError) as error:
            with upstream_slot(lock, connection, timeout_seconds=.01):
                pytest.fail('expired queue dispatched')
        assert error.value.status == 503
        assert error.value.category == 'local_queue_timeout'
        assert not lock.acquire(blocking=False)
    finally:
        lock.release(); connection.close(); client.close()


def test_live_client_releases_slot_after_upstream_failure():
    import socket, threading
    from tools.packy_responses_gateway import upstream_slot
    connection, client = socket.socketpair()
    lock = threading.BoundedSemaphore(1)
    try:
        with pytest.raises(RuntimeError):
            with upstream_slot(lock, connection):
                assert not lock.acquire(blocking=False)
                raise RuntimeError('fake upstream failure')
        assert lock.acquire(blocking=False)
    finally:
        connection.close(); client.close()

@pytest.mark.parametrize('separator', [b'data:', b'data: '])
def test_sse_optional_space_and_multiline_json(separator):
    import io
    telemetry={}
    body=separator+b'{"type":"response.completed",\n'+separator+b'"response":{"status":"completed","output":[]}}\n\n'
    assert read_responses_stream(io.BytesIO(body),telemetry=telemetry)['status']=='completed'
    assert telemetry['sse_events']==1
    assert telemetry['last_event_type']=='response.completed'


def test_real_http_stalled_stream_is_bounded_and_preserves_progress():
    import time, threading, urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.end_headers()
            self.wfile.write(b'data: {"type":"response.created"}\n\n');self.wfile.flush()
            time.sleep(.5)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True);thread.start()
    telemetry={}
    try:
        with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port),timeout=2) as response:
            started=time.monotonic()
            with pytest.raises(UpstreamStreamError) as error:read_responses_stream(response,.08,telemetry)
            assert time.monotonic()-started<.4
        assert error.value.status==504
        assert telemetry['last_event_type']=='response.created'
        assert telemetry['sse_events']==1
        assert telemetry['sse_bytes_read']>0
    finally:
        server.shutdown();server.server_close()


def test_stream_timeout_is_absolute_not_reset_by_heartbeat(monkeypatch):
    import io
    from tools import packy_responses_gateway as gateway
    clock=[0.0]
    class Stream:
        def __iter__(self):return self
        def __next__(self):
            clock[0]+=.04
            return b': heartbeat\n'
    monkeypatch.setattr(gateway.time,'monotonic',lambda:clock[0])
    with pytest.raises(UpstreamStreamError) as error:read_responses_stream(Stream(),.1)
    assert error.value.category=='upstream_total_deadline'
    assert clock[0]<.2


@pytest.mark.parametrize("native",[False,True])
def test_full_loopback_gateway_delivers_mock_sse_and_audits_stages(tmp_path,native):
    import sys, subprocess, socket, time, threading, urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    received=[]
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200);self.send_header('x-request-id','local-test');self.end_headers()
            events=[{'type':'response.output_item.done','output_index':0,'item':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'hello'}]}},
                    {'type':'response.completed','response':{'id':'test','status':'completed','output':[],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}}]
            self.wfile.write(''.join('data:'+json.dumps(x)+'\n\n' for x in events).encode())
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream);upstream.daemon_threads=True
    threading.Thread(target=lambda:upstream.serve_forever(poll_interval=.01),daemon=True).start()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    audit=tmp_path/'audit.jsonl'
    script='from pathlib import Path;from tools import packy_responses_gateway as g;g.UPSTREAM='+repr('http://127.0.0.1:'+str(upstream.server_port))+';g.serve(["local-test-key"],'+str(port)+',Path('+repr(str(audit))+'),1,upstream_timeout_seconds=1)'
    child=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    base='http://127.0.0.1:'+str(port)
    try:
        for _ in range(100):
            if child.poll() is not None:pytest.fail(child.stderr.read().decode())
            try:
                with urllib.request.urlopen(base+'/health',timeout=.1):break
            except OSError:time.sleep(.02)
        else:pytest.fail('mock gateway did not become healthy')
        payload={'model':'gpt-6.1-terra','messages':[{'role':'user','content':'test'}]}
        if native:payload={'model':'gpt-6.1-terra','instructions':'preserve original system exactly','input':[{'role':'user','content':'test'}],'stream':True}
        req=urllib.request.Request(base+('/v1/responses' if native else '/v1/chat/completions'),data=json.dumps(payload).encode(),headers={'Authorization':'Bearer local-test-key','Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=2) as response:
            if native:
                import io
                raw=response.read()
                assert raw.endswith(b'\n\n'), 'strict SSE parser would discard final completion event'
                frames=[json.loads(x.split(b'data:',1)[1]) for x in raw.split(b'\n\n')[:-1] if b'data:' in x]
                assert frames[-1]['type']=='response.completed'
                result=read_responses_stream(io.BytesIO(raw))
            else:result=json.load(response)
        if native:
            assert result['output'][0]['content'][0]['text']=='hello'
            assert received[0]['instructions']==payload['instructions']
            assert received[0]['input']==payload['input']
        else:assert result['choices'][0]['message']['content']=='hello'
        for _ in range(50):
            if audit.exists() and audit.read_text().strip():break
            time.sleep(.01)
        row=json.loads(audit.read_text().splitlines()[0])
        assert row['status']==200
        assert row['progress']['stage']==('native_stream_delivered' if native else 'client_delivery')
        assert row['progress']['upstream_dispatched'] is True
        assert row['progress']['last_event_type']=='response.completed'
        assert row['progress']['upstream_request_id']=='local-test'
    finally:
        child.terminate();child.wait(timeout=3)
        upstream.shutdown();upstream.server_close()


def test_dynamic_upstream_limit_preserves_existing_slots_on_downshift(tmp_path):
    from tools.packy_responses_gateway import AdaptiveUpstreamGate
    p=tmp_path/'policy.json';p.write_text('{"upstream_concurrency":2}')
    gate=AdaptiveUpstreamGate(p,16)
    assert gate.acquire(timeout=0) and gate.acquire(timeout=0)
    assert not gate.acquire(timeout=0)
    p.write_text('{"upstream_concurrency":4}')
    assert gate.acquire(timeout=0) and gate.acquire(timeout=0)
    p.write_text('{"upstream_concurrency":1}')
    assert not gate.acquire(timeout=0) and gate.active==4
    for _ in range(3):gate.release()
    assert not gate.acquire(timeout=0)
    gate.release();assert gate.acquire(timeout=0)
    p.write_text('{invalid')
    assert not gate.acquire(timeout=0) and gate.limit==1
    gate.release()
