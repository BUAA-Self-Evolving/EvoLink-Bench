import json,time
import pytest
from baseline.adapters.skillopt.native_l1_tools import run
from baseline.adapters.skillopt.bridge import _execute_dsml_tool

def call(name,args,id='c1'):
 return {'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}

def invoke(chat,execute,state=None,**options):
 return run([{'role':'system','content':'original system'},{'role':'user','content':'original task'}],chat=chat,execute=execute,state=state if state is not None else {'model_calls':0,'tool_calls':0},max_model_calls=options.get('models',12),max_tool_calls=options.get('tools',16),deadline=options.get('deadline',time.monotonic()+10),max_tokens=4096,retries=1,timeout=10)

def test_real_file_tools_are_exposed_and_results_keep_native_call_identity(tmp_path,monkeypatch):
 (tmp_path/'input.txt').write_text('source data');events=[]
 def chat(**kw):
  events.append(kw)
  assert kw['tools'] and kw['return_message'] and kw['tool_choice']=='auto'
  assert kw['messages'][0]['content']=='original system'
  if len(events)==1:return {'role':'assistant','content':None,'tool_calls':[call('Read',{'file_path':'/workspace/input.txt'},'read-original')]},{'prompt_tokens':10,'completion_tokens':2}
  if len(events)==2:
   assert kw['messages'][-1]=={'role':'tool','tool_call_id':'read-original','content':'source data'}
   return {'content':None,'tool_calls':[call('Write',{'file_path':'/workspace/output/result.txt','content':'derived artifact'},'write-original')]},{'prompt_tokens':12,'completion_tokens':3}
  return {'content':'Done','tool_calls':[]},{'prompt_tokens':15,'completion_tokens':4}
 monkeypatch.setenv('TRIEVO_API_TIMEOUT_SECONDS','300')
 state={'model_calls':0,'tool_calls':0}
 result=invoke(chat,lambda c:_execute_dsml_tool(c,tmp_path,{}),state)
 assert result['text']=='Done' and (tmp_path/'output/result.txt').read_text()=='derived artifact'
 assert state=={'model_calls':3,'tool_calls':2}
 assert result['usage']['prompt_tokens']==37 and not result['limit_reason']
 import os
 assert os.environ['TRIEVO_API_TIMEOUT_SECONDS']=='300'

def test_budget_is_shared_across_interactions_and_never_extra_format_retry():
 state={'model_calls':1,'tool_calls':0};seen=[]
 def chat(**kw):seen.append(kw);return {'tool_calls':[call('LS',{'path':'/workspace'})]},{}
 result=invoke(chat,lambda c:'listing',state,models=2)
 assert len(seen)==1 and result['limit_reason']=='max_model_calls'
 assert state['model_calls']==2

def test_tool_limit_stops_new_execution_without_repeating_reply():
 seen=[];models=[]
 def chat(**kw):models.append(kw);return {'tool_calls':[call('LS',{'path':'.'},'a'),call('LS',{'path':'.'},'b')]},{}
 result=invoke(chat,lambda c:seen.append(c) or 'ok',tools=1)
 assert len(seen)==len(models)==1 and result['limit_reason']=='max_tool_calls'

def test_invalid_path_is_a_tool_observation_not_a_transport_replay(tmp_path):
 seen=[]
 def chat(**kw):
  seen.append(kw)
  if len(seen)==1:return {'tool_calls':[call('Write',{'file_path':'../outside','content':'bad'})]},{}
  assert '[tool error]' in kw['messages'][-1]['content']
  return {'content':'Cannot write there'},{}
 invoke(chat,lambda c:_execute_dsml_tool(c,tmp_path,{}))
 assert not (tmp_path.parent/'outside').exists() and len(seen)==2

def test_exhausted_episode_makes_no_api_call():
 result=invoke(lambda **kw:pytest.fail('paid request'),lambda c:pytest.fail('tool'),deadline=time.monotonic()-1)
 assert result['limit_reason']=='episode_timeout'

def test_skillopt_compat_message_object_is_supported_without_a_paid_retry():
 class Message:
  def model_dump(self):return {'role':'assistant','content':'native compatible message','tool_calls':[]}
 result=invoke(lambda **kw:(Message(),{'total_tokens':7}),lambda c:pytest.fail('unexpected tool'))
 assert result['text']=='native compatible message' and result['usage']['total_tokens']==7

def test_transport_failure_does_not_hide_or_repeat_a_paid_request(monkeypatch):
 seen=[]
 def chat(**kw):seen.append(kw);raise RuntimeError('upstream failed')
 monkeypatch.setenv('TRIEVO_API_TIMEOUT_SECONDS','300')
 with pytest.raises(RuntimeError):invoke(chat,lambda c:'unused')
 import os
 assert len(seen)==1 and os.environ['TRIEVO_API_TIMEOUT_SECONDS']=='300'
