"""Pooled HTTP/2 SSE transport; no model retries or request logging."""
from __future__ import annotations
import asyncio
import json
import io
import queue
import threading
import time
import urllib.error

class _Response:
    def __init__(self, messages, future, timeout, terminal):
        self._messages,self._future,self._terminal=messages,future,terminal
        self._deadline=time.monotonic()+timeout
        self._read_deadline=self._deadline
        first=self._next()
        if not isinstance(first,tuple) or first[0]!='headers':
            self.close();raise RuntimeError('pooled transport missing response headers')
        _,self.status,self.headers,self.http_version=first
    def set_read_timeout(self,remaining):
        self._read_deadline=min(self._deadline,time.monotonic()+remaining)
    def _next(self):
        remaining=min(self._deadline,self._read_deadline)-time.monotonic()
        if remaining<=0:raise TimeoutError('pooled upstream transport deadline exceeded')
        try:item=self._messages.get(timeout=remaining)
        except queue.Empty as error:raise TimeoutError('pooled upstream read timed out') from error
        if isinstance(item,BaseException):raise item
        return item
    def __iter__(self):return self
    def __next__(self):
        item=self._next()
        if item is None:raise StopIteration
        return item
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        if not self._future.done() and not self._terminal.is_set():self._future.cancel()

class PooledResponsesTransport:
    def __init__(self,max_connections=32,client=None,proxy=None,http2=True,client_factory=None):
        self._loop=asyncio.new_event_loop()
        self._thread=threading.Thread(target=self._loop.run_forever,daemon=True)
        self._thread.start()
        self._active=0;self._reset_pending=False;self._resets=0;self._last_timeout_type=None
        self._can_reset=client is None or client_factory is not None
        async def initialize():
            if client_factory is not None:return await client_factory()
            import httpx
            limits=httpx.Limits(max_connections=max_connections,max_keepalive_connections=max_connections,keepalive_expiry=120)
            transport=httpx.AsyncHTTPTransport(http2=http2,local_address='0.0.0.0',limits=limits,retries=0,proxy=proxy)
            return httpx.AsyncClient(transport=transport,http2=http2,trust_env=False,follow_redirects=False,headers={'Accept':'text/event-stream','Accept-Encoding':'identity'})
        self._factory=initialize
        async def first():return client if client is not None else await initialize()
        self._client=asyncio.run_coroutine_threadsafe(first(),self._loop).result(timeout=5)
    async def _stream(self,request,timeout,messages,terminal):
        import httpx
        self._active+=1
        try:
            async with asyncio.timeout(timeout):
                async with self._client.stream(request.get_method(),request.full_url,
                    content=request.data,headers=dict(request.header_items()),
                    timeout=httpx.Timeout(timeout,connect=min(15,timeout),write=min(30,timeout),pool=min(10,timeout))) as response:
                    if response.status_code>=300:
                        body=bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk[:max(0,4096-len(body))])
                            if len(body)>=4096:break
                        messages.put(urllib.error.HTTPError(request.full_url,response.status_code,response.reason_phrase,dict(response.headers),io.BytesIO(body)))
                        return
                    messages.put(('headers',response.status_code,dict(response.headers),response.http_version))
                    size=0
                    async for line in response.aiter_lines():
                        raw=line.encode('utf-8')+b'\n';size+=len(raw)
                        if size>32*1024*1024:raise ValueError('upstream response exceeded transport size bound')
                        is_terminal=False
                        if line.startswith('data:'):
                            try:is_terminal=json.loads(line[5:].strip()).get('type') in ('response.completed','response.incomplete','response.failed','error')
                            except (ValueError,AttributeError):pass
                        if is_terminal:terminal.set()
                        messages.put(raw)
                        if is_terminal:break
        except (TimeoutError,httpx.TimeoutException) as error:
            self._last_timeout_type=type(error).__name__
            if isinstance(error,httpx.PoolTimeout):self._reset_pending=True
            wrapped=TimeoutError('pooled upstream '+type(error).__name__);wrapped.__cause__=error
            messages.put(wrapped)
        except Exception as error:messages.put(error)
        finally:
            self._active-=1;messages.put(None)
            # Replace only a locally exhausted pool after all owned model streams
            # have ended. Never replay this failed request or cancel paid peers.
            if self._reset_pending and self._active==0 and self._can_reset:
                old=self._client
                self._client=await self._factory()
                self._reset_pending=False;self._resets+=1
                try:await asyncio.wait_for(old.aclose(),timeout=2)
                except (Exception,asyncio.CancelledError):pass
    def open(self,request,timeout=120):
        messages=queue.Queue();terminal=threading.Event()
        future=asyncio.run_coroutine_threadsafe(self._stream(request,timeout,messages,terminal),self._loop)
        try:return _Response(messages,future,timeout,terminal)
        except BaseException:
            future.cancel();raise
    def diagnostics(self):
        result={'active_streams':self._active,'idle_pool_resets':self._resets,'pool_reset_pending':self._reset_pending,'last_timeout_type':self._last_timeout_type}
        pool=getattr(getattr(self._client,'_transport',None),'_pool',None)
        if pool is not None:
            for name in ('_requests','_connections'):
                value=getattr(pool,name,None)
                if isinstance(value,list):result['pool'+name+'_count']=len(value)
        return result
    def warmup(self,url):
        async def request():
            response=await self._client.get(url,timeout=10)
            return {'status':response.status_code,'http_version':response.http_version,'unauthenticated':True}
        return asyncio.run_coroutine_threadsafe(request(),self._loop).result(timeout=12)
    def close(self):
        async def shutdown():
            tasks=[t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            await self._loop.shutdown_asyncgens()
            await self._client.aclose()
        asyncio.run_coroutine_threadsafe(shutdown(),self._loop).result(timeout=5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if not self._thread.is_alive():
            self._loop.close()
