import io
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tools import openai_ssh_relay as relay


@pytest.mark.parametrize("status", [200, 429, 502, 302])
def test_relay_preserves_official_request_and_response_without_replay(monkeypatch, status):
    captured = []
    payload = b'{"model":"gpt-6-luna","stream":true}'
    body = b'data: {"type":"response.completed"}\n\n'

    def upstream(request, timeout):
        captured.append((request.full_url, request.data, request.get_header("Authorization")))
        if status == 502:
            raise urllib.error.URLError("TLS failure")
        if status in {429, 302}:
            raise urllib.error.HTTPError(request.full_url, status, "error",
                {"Content-Type": "text/event-stream", "Location": "http://untrusted.invalid"}, io.BytesIO(body))
        response = io.BytesIO(body)
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream"}
        return response

    monkeypatch.setattr(relay, "official_request", upstream)
    server = ThreadingHTTPServer(("127.0.0.1", 0), relay.Handler)
    server.upstream_timeout = 5
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/responses",
            data=payload, headers={"Authorization": "Bearer fake-test-only"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            assert response.status == (502 if status == 302 else status)
            if status in {200, 429}:
                assert response.read() == body
        assert captured == [("https://api.openai.com/v1/responses", payload, "Bearer fake-test-only")]
    finally:
        server.shutdown()
        server.server_close()
