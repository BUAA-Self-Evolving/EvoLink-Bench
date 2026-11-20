"""Loopback-only transport relay to the official OpenAI API.

Forward this listener through an authenticated SSH tunnel. Request bodies and
authorization headers are passed unchanged. Buffer each upstream response so
the remote client's SSE transport never depends on the remote TLS stack.
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error

MAX_BYTES = 64 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def official_request(request, timeout):
    return urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)


def response_body(response, timeout):
    if "text/event-stream" not in response.headers.get("Content-Type", ""):
        return response.read(MAX_BYTES + 1)
    chunks, count, terminal = [], 0, False
    deadline = time.monotonic() + timeout
    for line in response:
        if time.monotonic() > deadline:
            raise TimeoutError("Upstream SSE deadline exceeded")
        chunks.append(line)
        count += len(line)
        if count > MAX_BYTES:
            break
        if line.startswith(b"data:"):
            data = line[5:].strip()
            if data == b"[DONE]":
                terminal = True
            else:
                try:
                    event = json.loads(data)
                    terminal = event.get("type") in {"response.completed", "response.failed", "response.incomplete"}
                except (ValueError, AttributeError):
                    pass
        if terminal and not line.strip():
            break
    return b"".join(chunks)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BYTES:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else None
        omitted = {"host", "connection", "content-length", "transfer-encoding",
                   "accept-encoding", "proxy-authorization", "proxy-connection"}
        headers = {key: value for key, value in self.headers.items() if key.lower() not in omitted}
        request = urllib.request.Request("https://api.openai.com" + self.path,
            data=body, headers=headers, method=self.command)
        try:
            try:
                response = official_request(request, timeout=self.server.upstream_timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    self.send_error(502, "Unexpected official API redirect")
                    return
                response = exc
            with response:
                data = response_body(response, self.server.upstream_timeout)
                if len(data) > MAX_BYTES:
                    self.send_error(502, "Upstream response exceeded relay limit")
                    return
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in {"connection", "content-length", "transfer-encoding", "server", "date"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (urllib.error.URLError, OSError, TimeoutError):
            try:
                self.send_error(502, "Official API upstream transport failed")
            except OSError:
                pass
        finally:
            self.close_connection = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.upstream_timeout = args.timeout
    server.serve_forever()
