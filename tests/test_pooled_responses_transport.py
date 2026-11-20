import asyncio
import concurrent.futures
import io
import json
import time
import urllib.request
import urllib.error
import pytest
httpx=pytest.importorskip("httpx")
from tools.pooled_responses_transport import PooledResponsesTransport
from tools.packy_responses_gateway import read_responses_stream,UpstreamStreamError

BODY=b'data:{"type":"response.completed","response":{"status":"completed","output":[],"usage":{"total_tokens":2}}}\n\n'
def request():return urllib.request.Request('https://example.invalid/responses',data=b'{}',headers={'Authorization':'Bearer local-test'})
def test_pooled_transport_preserves_stream_and_metadata():
 client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=BODY,headers={'x-request-id':'mock'})))
 t=PooledResponsesTransport(client=client)
 try:
  with t.open(request(),timeout=1) as response:
   assert response.status==200
   assert response.headers['x-request-id']=='mock'
   assert read_responses_stream(response)['usage']['total_tokens']==2
 finally:t.close()

def test_pooled_transport_preserves_funding_http_error_without_retry():
 calls=[]
 def handler(req):calls.append(req);return httpx.Response(402,content=b'funding')
 t=PooledResponsesTransport(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
 try:
  with pytest.raises(urllib.error.HTTPError) as error:t.open(request(),timeout=1)
  assert error.value.code==402 and error.value.read()==b'funding'
  assert len(calls)==1
 finally:t.close()

def test_pooled_stream_silence_obeys_reader_deadline_and_cancels_only_that_stream():
 class Stalled(httpx.AsyncByteStream):
  async def __aiter__(self):
   yield b'data:{"type":"response.created"}\n\n'
   await asyncio.sleep(.5)
 t=PooledResponsesTransport(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=Stalled()))))
 try:
  with t.open(request(),timeout=1) as response:
   start=time.monotonic()
   with pytest.raises(UpstreamStreamError) as error:read_responses_stream(response,.05)
   assert error.value.status==504
   assert time.monotonic()-start<.3
 finally:t.close()

def test_pooled_concurrent_requests_share_client_without_replaying():
 active=0;peak=0;calls=0
 async def handler(req):
  nonlocal active,peak,calls
  calls+=1;active+=1;peak=max(peak,active)
  await asyncio.sleep(.05);active-=1
  return httpx.Response(200,content=BODY)
 t=PooledResponsesTransport(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
 def one(i):
  with t.open(request(),timeout=2) as response:return read_responses_stream(response)['status']
 try:
  with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:assert list(pool.map(one,range(12)))==['completed']*12
  assert peak>=10 and calls==12
 finally:t.close()


def test_completed_response_stops_producer_without_waiting_for_stream_eof():
 closed=[]
 class AfterCompletion(httpx.AsyncByteStream):
  async def __aiter__(self):
   yield BODY
   await asyncio.sleep(10)
   pytest.fail('producer read beyond completed response')
  async def aclose(self):closed.append(True)
 t=PooledResponsesTransport(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=AfterCompletion()))))
 try:
  with t.open(request(),timeout=1) as response:
   assert read_responses_stream(response)['status']=='completed'
  for _ in range(50):
   if closed:break
   time.sleep(.01)
  assert closed
 finally:t.close()


def test_pool_timeout_resets_idle_pool_without_replaying_failed_model_request():
 calls=[];factories=[]
 async def factory():
  index=len(factories);factories.append(index)
  def handler(req):
   calls.append(index)
   if index==0:raise httpx.PoolTimeout('private upstream credential detail')
   return httpx.Response(200,content=BODY)
  return httpx.AsyncClient(transport=httpx.MockTransport(handler))
 t=PooledResponsesTransport(client_factory=factory)
 try:
  with pytest.raises(TimeoutError) as failure:t.open(request(),timeout=2)
  assert isinstance(failure.value.__cause__,httpx.PoolTimeout)
  for _ in range(100):
   if t.diagnostics()['idle_pool_resets']:break
   time.sleep(.005)
  assert calls==[0] and factories==[0,1]  # Failed request was never retried.
  with t.open(request(),timeout=2) as response:assert read_responses_stream(response)['status']=='completed'
  assert calls==[0,1]
 finally:t.close()

def test_pool_reset_waits_for_paid_peer_to_finish_naturally():
 import threading
 entered=threading.Event();release=threading.Event();factories=[];completed=[]
 async def factory():
  index=len(factories);factories.append(index)
  async def handler(req):
   if req.url.path=='/slow':
    entered.set()
    while not release.is_set():await asyncio.sleep(.005)
    completed.append('paid_peer_finished')
    return httpx.Response(200,content=BODY)
   raise httpx.PoolTimeout('pool exhausted')
  return httpx.AsyncClient(transport=httpx.MockTransport(handler))
 t=PooledResponsesTransport(client_factory=factory)
 def slow():
  with t.open(urllib.request.Request('https://example.invalid/slow',data=b'{}'),timeout=3) as response:return read_responses_stream(response)['status']
 try:
  with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
   peer=pool.submit(slow);assert entered.wait(1)
   with pytest.raises(TimeoutError):t.open(request(),timeout=2)
   assert t.diagnostics()['active_streams']==1 and t.diagnostics()['idle_pool_resets']==0
   release.set();assert peer.result(timeout=2)=='completed'
  for _ in range(100):
   if t.diagnostics()['idle_pool_resets']:break
   time.sleep(.005)
  assert completed==['paid_peer_finished'] and t.diagnostics()['idle_pool_resets']==1
 finally:release.set();t.close()

def test_failure_diagnostics_never_contains_error_message_or_key():
 from tools.packy_responses_gateway import transport_diagnostics
 e=TimeoutError('private prompt and credential');e.__cause__=httpx.PoolTimeout('private token')
 d=transport_diagnostics(None,e)
 assert d=={'exception_chain':[{'type':'TimeoutError'},{'type':'PoolTimeout'}]}
 assert 'private' not in json.dumps(d)
