"""Loopback-only Chat/Responses compatibility for the PackyCode Terra experiment.

No task prompts or credentials are logged. Chat streams are explicitly buffered
until a complete Responses result is received, then emitted as Chat SSE chunks.
This is transport compatibility, not an alternate agent or tool executor.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import select
import socket
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

MODEL = "gpt-6.1-terra"
UPSTREAM = "https://cf.api.fan/v1"


class UpstreamStreamError(ValueError):
    def __init__(self, error: dict):
        self.error = error
        category = str(error.get('code') or error.get('type') or '').lower()
        message = str(error.get('message') or 'upstream Responses stream failed')
        self.category = category or 'stream_error'
        if category in ('upstream_read_timeout', 'upstream_total_deadline'):
            self.status = 504
        elif category == 'local_queue_timeout':
            self.status = 503
        elif category == 'client_disconnected':
            self.status = 499
        elif any(value in category for value in ('insufficient_quota', 'balance', 'credit')):
            self.status = 402
        elif 'rate_limit' in category or 'rate limit' in message.lower():
            self.status = 429
        elif category in ('invalid_request_error', 'context_length_exceeded', 'invalid_request'):
            self.status = 400
        else:
            self.status = 502
        super().__init__(message)


def responses_request(chat: dict) -> dict:
    if chat.get("model") != MODEL:
        raise ValueError("only the experiment's exact model is allowed")
    items, instructions = [], []
    for message in chat.get("messages", []):
        role = message["role"]
        if role in {"system", "developer"}:
            content = message.get("content", "")
            if isinstance(content, list):
                content = "\n".join(part["text"] for part in content if part.get("type") == "text")
            instructions.append(content)
            continue
        if role == "tool":
            content = message.get("content", "")
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                          "output": content if isinstance(content, str) else json.dumps(content)})
            continue
        content = message.get("content")
        if isinstance(content, list):
            converted = []
            for part in content:
                if part.get("type") == "text":
                    converted.append({"type": "output_text" if role == "assistant" else "input_text",
                                      "text": part["text"]})
                elif part.get("type") == "image_url" and role != "assistant":
                    image = part["image_url"]
                    converted.append({"type": "input_image", "image_url": image["url"],
                                      **({"detail": image["detail"]} if "detail" in image else {})})
                else:
                    raise ValueError("unsupported message content part")
            content = converted
        if content:
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            if call.get("type") != "function":
                raise ValueError("unsupported tool call type")
            items.append({"type": "function_call", "call_id": call["id"],
                          "name": call["function"]["name"],
                          "arguments": call["function"]["arguments"]})
    result = {"model": MODEL, "input": items, "store": False, "stream": False}
    result["instructions"] = "\n\n".join(instructions)
    cap = chat.get("max_completion_tokens", chat.get("max_tokens"))
    if cap is not None:
        result["max_output_tokens"] = cap
    effort = chat.get("reasoning_effort")
    if not effort:
        effort = "medium" if chat.get("thinking", {}).get("type") == "enabled" else "none"
    result["reasoning"] = {"effort": effort}
    # PackyCode's Terra routes can reject temperature even with effort=none.
    # Omit it consistently rather than retrying an already generated answer.
    if chat.get("tools"):
        tools = []
        for tool in chat["tools"]:
            if tool.get("type") != "function":
                raise ValueError("unsupported tool type")
            tools.append({"type": "function", "strict": False, **tool["function"]})
        result["tools"] = tools
    choice = chat.get("tool_choice")
    if choice is not None:
        result["tool_choice"] = ({"type": "function", "name": choice["function"]["name"]}
                                 if isinstance(choice, dict) else choice)
    for name in ("parallel_tool_calls", "prompt_cache_key"):
        if name in chat:
            result[name] = chat[name]
    if chat.get("response_format"):
        fmt = chat["response_format"]
        if fmt["type"] == "json_schema":
            fmt = {"type": "json_schema", **fmt["json_schema"]}
        result["text"] = {"format": fmt}
    return result


def chat_result(response: dict) -> dict:
    status = response.get("status")
    if status not in {"completed", "incomplete"}:
        raise ValueError("upstream response did not finish successfully")
    text, calls = [], []
    for item in response.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text.append(part["text"])
                elif part.get("type") == "refusal":
                    text.append(part.get("refusal", ""))
        elif item.get("type") == "function_call":
            calls.append({"id": item["call_id"], "type": "function", "function": {
                "name": item["name"], "arguments": item["arguments"]}})
    usage = response.get("usage") or {}
    inp, out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    return {"id": response.get("id", "compat-response"), "object": "chat.completion",
        "created": response.get("created_at", int(time.time())), "model": response.get("model", MODEL),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(text) or None,
                      **({"tool_calls": calls} if calls else {})},
                     "finish_reason": "length" if status == "incomplete" else "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": inp, "completion_tokens": out,
                  "total_tokens": usage.get("total_tokens", inp + out),
                  "prompt_tokens_details": usage.get("input_tokens_details", {}),
                  "completion_tokens_details": usage.get("output_tokens_details", {})}}


def chat_sse(result: dict) -> bytes:
    base = {key: result[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    choice = result["choices"][0]
    delta = dict(choice["message"])
    if delta.get("tool_calls"):
        delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(delta["tool_calls"])]
    chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
              {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]},
              {**base, "choices": [], "usage": result["usage"]}]
    return ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()


def _response_socket_timeout(response, remaining):
    setter = getattr(response, 'set_read_timeout', None)
    if callable(setter):
        setter(remaining)
        return
    for candidate in (getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None),
                      getattr(getattr(response, 'fp', None), 'raw', None), getattr(response, 'fp', None)):
        setter = getattr(candidate, 'settimeout', None)
        if callable(setter):
            setter(max(.001, remaining))
            return


def read_responses_stream(response, timeout_seconds: float = 120, telemetry=None, on_line=None) -> dict:
    """Read bounded SSE, preserving output_item.done and content-free progress evidence."""
    telemetry = telemetry if telemetry is not None else {}
    telemetry.update(sse_bytes_read=0, sse_events=0, last_event_type=None)
    items, data_lines = {}, []
    started = time.monotonic()
    deadline = started + timeout_seconds
    iterator = iter(response)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpstreamStreamError({'code':'upstream_total_deadline','message':'upstream response stream exceeded remaining transport deadline'})
        _response_socket_timeout(response, remaining)
        try:
            line = next(iterator)
        except StopIteration:
            break
        except TimeoutError as exc:
            raise UpstreamStreamError({'code':'upstream_read_timeout','message':'timed out reading upstream response stream'}) from exc
        if on_line is not None:on_line(line)
        telemetry['sse_bytes_read'] += len(line)
        if telemetry['sse_bytes_read'] > 32*1024*1024:
            raise UpstreamStreamError({'code':'upstream_stream_size_exceeded','message':'upstream response exceeded transport size bound'})
        if not line.startswith(b'data:'):
            if not line.strip() and data_lines:
                raise UpstreamStreamError({'code':'invalid_sse_event','message':'upstream SSE event contained invalid JSON'})
            continue
        data = line[5:].removeprefix(b' ').rstrip(b'\r\n')
        if data.strip() == b'[DONE]':
            continue
        data_lines.append(data)
        try:
            event = json.loads(b'\n'.join(data_lines))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # SSE JSON may span more than one data: line.
        data_lines = []
        if not isinstance(event, dict):
            raise UpstreamStreamError({'code':'invalid_sse_event','message':'upstream SSE event is not an object'})
        telemetry['sse_events'] += 1
        telemetry['last_event_type'] = event.get('type')
        telemetry['last_event_seconds'] = round(time.monotonic()-started,3)
        if event.get('type') == 'response.output_item.done':
            items[event['output_index']] = event['item']
        elif event.get('type') in {'response.completed','response.incomplete'}:
            result = event['response']
            if items:result['output'] = [items[i] for i in sorted(items)]
            return result
        elif event.get('type') in {'error','response.failed'}:
            error = event.get('error') or (event.get('response') or {}).get('error') or event
            raise UpstreamStreamError({key:error[key] for key in ('code','type','message','param') if key in error})
    raise UpstreamStreamError({'code':'incomplete_stream','message':'upstream Responses stream ended before completion'})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def upstream_slot(lock, connection, *, timeout_seconds=30):
    """Expire unbilled queue entries and never dispatch for a disconnected client."""
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        while not acquired:
            if select.select([connection], [], [], 0)[0]:
                if not connection.recv(1, socket.MSG_PEEK):
                    raise UpstreamStreamError({'code': 'client_disconnected', 'message': 'client disconnected before upstream dispatch'})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UpstreamStreamError({'code': 'local_queue_timeout', 'message': 'upstream admission queue deadline exceeded; no upstream request sent'})
            acquired = lock.acquire(timeout=min(.25, remaining))
        # The client can disconnect just as an upstream slot becomes available.
        if select.select([connection], [], [], 0)[0] and not connection.recv(1, socket.MSG_PEEK):
            raise UpstreamStreamError({'code': 'client_disconnected', 'message': 'client disconnected before upstream dispatch'})
        yield
    finally:
        if acquired:
            lock.release()


class AdaptiveUpstreamGate:
    """Change admission width without interrupting existing upstream requests."""
    def __init__(self,path,initial):
        self.path=Path(path);self.limit=initial;self.active=0;self.condition=threading.Condition()
    def acquire(self,timeout=None):
        with self.condition:
            try:
                value=json.loads(self.path.read_text()).get('upstream_concurrency')
                if type(value) is int and 1<=value<=64:self.limit=value
            except (OSError,ValueError,AttributeError):pass
            if self.active<self.limit:self.active+=1;return True
            self.condition.wait(timeout)
            return False
    def release(self):
        with self.condition:
            if self.active<=0:raise RuntimeError('unbalanced upstream admission release')
            self.active-=1;self.condition.notify_all()


def transport_diagnostics(transport,exc=None):
    # Exception class/errno only; never credentials, exception bodies, or prompts.
    result={};chain=[];seen=set()
    while exc is not None and id(exc) not in seen and len(chain)<6:
        seen.add(id(exc));item={'type':type(exc).__name__}
        errno=getattr(exc,'errno',None)
        if type(errno) is int:item['errno']=errno
        chain.append(item);exc=exc.__cause__ or exc.__context__
    if chain:result['exception_chain']=chain
    method=getattr(transport,'diagnostics',None)
    if callable(method):result['pool']=method()
    return result

def serve(keys: list[str], port: int, audit: Path, upstream_concurrency: int = 1,
          upstream_timeout_seconds: float = 120, queue_timeout_seconds: float = 30, transport=None, concurrency_policy_path=None):
    lock = AdaptiveUpstreamGate(concurrency_policy_path,upstream_concurrency) if concurrency_policy_path else threading.BoundedSemaphore(upstream_concurrency)
    opener = transport or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_body(self, status, body, content_type="application/json"):
            try:
                if getattr(self,'_native_started',False):
                    error = json.loads(body).get('error',{'message':'upstream stream failed'})
                    self.wfile.write(b'data: '+json.dumps({'type':'error','error':error}).encode()+b'\n\n')
                    self.wfile.flush()
                    return True
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            except (ConnectionError, TimeoutError):
                return False

        def do_GET(self):
            if self.path == "/health":
                self.send_body(200,json.dumps({'ok':True,'transport':'responses-buffered-chat','diagnostics':transport_diagnostics(opener)}).encode())
            else:
                self.send_body(404, b'{}')

        def do_POST(self):
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not any(hmac.compare_digest(token, key) for key in keys):
                self.send_body(401, b'{"error":{"message":"unauthorized"}}')
                return
            if self.path not in ("/v1/chat/completions", "/v1/responses"):
                self.send_body(404, b'{}')
                return
            status, usage, started = 500, {}, time.monotonic()
            error_category = None
            progress = {'stage':'request_validation','upstream_dispatched':False}
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32 * 1024 * 1024:
                    raise ValueError("invalid request size")
                original = json.loads(self.rfile.read(length))
                native_stream = self.path == '/v1/responses' and bool(original.get('stream'))
                translated = responses_request(original) if self.path.endswith("completions") else original
                if translated.get("model") != MODEL:
                    raise ValueError("unexpected model")
                translated['stream'] = True
                if native_stream:translated.pop('store',None)
                raw = json.dumps(translated).encode()
                request = urllib.request.Request(UPSTREAM + "/responses", data=raw,
                    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                progress['stage'] = 'queue'
                with upstream_slot(lock, self.connection, timeout_seconds=queue_timeout_seconds):
                    progress['queue_seconds'] = round(time.monotonic()-started,3)
                    progress['stage'] = 'upstream_headers'
                    progress['upstream_dispatched'] = True
                    remaining = max(1, upstream_timeout_seconds - (time.monotonic() - started))
                    with opener.open(request, timeout=remaining) as response:
                        progress['stage'] = 'upstream_stream'
                        progress['headers_seconds'] = round(time.monotonic()-started,3)
                        progress['upstream_http_status'] = response.status
                        progress['upstream_http_version'] = getattr(response,'http_version','HTTP/1.1')
                        for name in ('x-request-id','request-id'):
                            if response.headers.get(name):progress['upstream_request_id'] = response.headers[name][:128];break
                        remaining = upstream_timeout_seconds-(time.monotonic()-started)
                        if remaining <= 0:raise UpstreamStreamError({'code':'upstream_total_deadline','message':'upstream headers exhausted transport deadline'})
                        native_delivery = [True]
                        callback = None
                        if native_stream:
                            self.send_response(200)
                            self.send_header('Content-Type','text/event-stream')
                            self.send_header('Cache-Control','no-cache')
                            self.send_header('Connection','close')
                            self.end_headers()
                            self._native_started = True
                            self.close_connection = True
                            def callback(line):
                                if not native_delivery[0]:return
                                try:self.wfile.write(line);self.wfile.flush()
                                except (ConnectionError,TimeoutError):native_delivery[0]=False
                        result = read_responses_stream(response, timeout_seconds=min(270, remaining), telemetry=progress,on_line=callback)
                    body = json.dumps(result).encode()
                    usage = result.get("usage") or {}
                if native_stream:
                    # The parser returns on the completed data line before consuming
                    # its following SSE delimiter. Strict SDKs need the blank line.
                    callback(b'\n')
                    status = 200 if native_delivery[0] else 499
                    if not native_delivery[0]:error_category='client_disconnected_after_response'
                    progress['stage']='native_stream_delivered'
                    return
                if self.path.endswith('completions'):
                    result = chat_result(result)
                    if original.get("stream"):
                        body = chat_sse(result)
                    else:
                        body = json.dumps(result).encode()
                elif original.get("stream"):
                    raise ValueError("native Responses streaming must use provider directly")
                status = 200
                progress['stage'] = 'client_delivery'
                if not self.send_body(200, body, 'text/event-stream' if original.get('stream') else 'application/json'):
                    status,error_category = 499,'client_disconnected_after_response'
            except urllib.error.HTTPError as exc:
                error_category = 'upstream_http_error'
                status = exc.code
                body = exc.read(4096)
                for key in keys:
                    body = body.replace(key.encode(), b'[redacted]')
                self.send_body(status, body)
            except UpstreamStreamError as exc:
                status = exc.status
                error_category = exc.category
                body = json.dumps({'error': exc.error}).encode()
                for key in keys:
                    body = body.replace(key.encode(), b'[redacted]')
                self.send_body(status, body)
            except ValueError as exc:
                status = 400
                self.send_body(status, json.dumps({"error": {"message": str(exc)}}).encode())
            except TimeoutError as exc:
                status,error_category = 504,'upstream_read_timeout'
                progress['exception_type'] = type(exc).__name__
                progress.update(transport_diagnostics(opener,exc))
                self.send_body(status, b'{"error":{"code":"upstream_read_timeout","message":"upstream transport timed out"}}')
            except Exception as exc:
                progress['exception_type'] = type(exc).__name__
                progress.update(transport_diagnostics(opener,exc))
                error_category = 'gateway_transport_error'
                status = 502
                self.send_body(status, json.dumps({"error": {"message": type(exc).__name__}}).encode())
            finally:
                with audit.open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"time": time.time(), "route": self.path, "status": status,
                        "seconds": round(time.monotonic() - started, 3), "usage": usage,
                        "error_category": error_category, "progress": progress}) + "\n")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18866)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--upstream-concurrency", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.upstream_concurrency <= 64:
        parser.error("upstream concurrency must be in 1..64")
    serve(json.loads(args.keys_file.read_text()), args.port, args.audit, args.upstream_concurrency)
