from pathlib import Path
import copy,json,zipfile,hashlib
import pytest
from tools import l1_rejected_learning as m

def put(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
def bundle(p,entries):
 p.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(p,'w') as z:
  for k,v in entries.items():z.writestr(k,v)

@pytest.fixture
def sample(tmp_path):
 out=tmp_path/'original';cp=out/'_checkpoints'/'x'/'t0001';flow=out/'flow'
 row={'id':'l1/evolving/adaptive-auto-harness/s10','agent':'adaptive-auto-harness','level':'l1','condition':'evolving','status':'paused_error','output':str(out),'flow_id':'flow','turns':['turn1','turn2','turn3'],'log':str(out/'driver.log')}
 prefix=[{'turn_id':'turn1','score':.3,'passed':False,'interactions':[],'evolution':{}}]
 put(cp/'checkpoint.json',{'flow_id':'flow','baseline':row['agent'],'condition':'evolving','completed_turn_index':0,'next_turn_index':1,'turn_id':'turn1','token_budget':{'limit':10000,'used':100,'calls':4},'exact_baseline_state':True})
 put(cp/'completed_turns.json',prefix);bundle(cp/'workspace.zip',{'old':'a'});bundle(cp/'baseline_state.zip',{'memory/m.json':'original','.trievo_semantic_state.json':'{}'})
 workspace=tmp_path/'restored';workspace.mkdir();(workspace/'answer.csv').write_bytes(b'answer')
 snapshot=[{'path':'answer.csv','size':6,'sha256':hashlib.sha256(b'answer').hexdigest()}]
 record={'turn_id':'turn2','index':1,'request':'q','response':'saved paid answer','score':1.0,'passed':True,'action_error':None,'verifier_details':{},'sandbox':{'files':snapshot},'usage':{'total_tokens':50,'api_calls':2}}
 flow.mkdir(parents=True);(flow/'live_trace.jsonl').write_text(json.dumps(record)+'\n')
 (out/'driver.log').write_text('evolink_bench.baselines.process.BaselineProtocolError: baseline adapter evolve failed: Extra data: line 8 column 1 (char 9)\n')
 failed=flow/'failed_evolution'/'abc';bundle(failed/'baseline_state.zip',{'memory/m.json':'original','.trievo_semantic_state.json':'{"different":"metadata"}'})
 snap=m.snapshot_from_checkpoint(cp/'baseline_state.zip');put(failed/'failure.json',{'turn_id':'turn2','recoverable_checkpoint':False,'state_digest':snap['digest']});put(failed/'baseline_state_snapshot.json',snap)
 review=tmp_path/'restoration.json';put(review,{'results':[{'job':row['id'],'file_count':1,'exact_original_post_answer_snapshot_restored':True}]})
 auth=tmp_path/'authority.json';put(auth,{'schema':m.SCHEMA,'job':row['id'],'policy':'original_answer_preserved_failed_learning_not_retried','workspace_policy':'exact_post_answer_snapshot_independent_recovery','post_failure_workspace_identity_claimed':False,'failed_learning_usage':'unknown','additional_learning_attempts':0})
 return row,review,workspace,auth,cp

def inspect(s):return m.inspect(*s[:4])

def test_preserves_answer_failed_learning_unknown_and_original_counter_floor(sample,tmp_path):
 row,*_=sample;proof,prefix,pending=inspect(sample);assert proof['derived_known_budget_lower_bound']=={'limit':10000,'used':150,'calls':6}
 result=m.materialize(row,(proof,prefix,pending),tmp_path/'branch');cp=Path(result['checkpoint']);turns=m.load(cp/'completed_turns.json');assert turns[:-1]==prefix;assert turns[-1]['score']==1 and turns[-1]['passed'] is True
 evo=turns[-1]['evolution'];assert evo['completed'] is False and evo['usage_status']=='unknown_original_failed_learning';assert evo['independent_recovery']['exact_post_failure_workspace_claimed'] is False
 assert (cp/'baseline_state.zip').read_bytes()==(sample[-1]/'baseline_state.zip').read_bytes()
 with pytest.raises(ValueError,match='already exists'):m.materialize(row,(proof,prefix,pending),tmp_path/'branch')

@pytest.mark.parametrize('key,value',[('failed_learning_usage','zero'),('additional_learning_attempts',1),('post_failure_workspace_identity_claimed',True)])
def test_rejects_false_policy(sample,key,value):
 d=m.load(sample[3]);d[key]=value;put(sample[3],d)
 with pytest.raises(ValueError):inspect(sample)

def test_changed_task_rejected(sample):
 (sample[2]/'answer.csv').write_bytes(b'different')
 with pytest.raises(ValueError,match='task bytes'):inspect(sample)

def test_changed_declared_learner_rejected(sample):
 f=Path(sample[0]['output'])/'flow/failed_evolution/abc/baseline_state.zip';bundle(f,{'memory/m.json':'mutated'})
 with pytest.raises(ValueError,match='learned files changed'):inspect(sample)

def test_duplicate_pending_rejected(sample):
 f=Path(sample[0]['output'])/'flow/live_trace.jsonl';f.write_text(f.read_text()*2)
 with pytest.raises(ValueError,match='duplicate'):inspect(sample)

def test_does_not_accept_original_failed_answer(sample):
 f=Path(sample[0]['output'])/'flow/live_trace.jsonl';d=json.loads(f.read_text());d.update(score=0,passed=False);f.write_text(json.dumps(d)+'\n')
 with pytest.raises(ValueError,match='successful terminal'):inspect(sample)

def test_forged_floor_rejected_before_output(sample,tmp_path):
 review=inspect(sample);review[0]['derived_known_budget_lower_bound']['calls']=0
 with pytest.raises(ValueError,match='forged'):m.materialize(sample[0],review,tmp_path/'branch')
 assert not (tmp_path/'branch').exists()

def test_new_paid_frontier_rejected(sample):
 f=Path(sample[0]['output'])/'flow/live_trace.jsonl';d=json.loads(f.read_text());d['turn_id']='turn3';f.write_text(f.read_text()+json.dumps(d)+'\n')
 with pytest.raises(ValueError,match='later paid'):inspect(sample)

def test_independent_failed_learning_retains_success_and_is_tagged(sample,tmp_path):
 from tools.audit_matrix_scores import learning_tags,transcript_check,TraceReader
 row=sample[0];result=m.materialize(row,inspect(sample),tmp_path/'branch');turn=m.load(Path(result['checkpoint'])/'completed_turns.json')[-1]
 assert learning_tags(turn)['derived_bounded_failure'] is True
 assert learning_tags(turn)['completed'] is False
 assert transcript_check(row,turn,Path(result['checkpoint'])/'completed_turns.json',TraceReader())['verified'] is True
 assert turn['passed'] is True and turn['score']==1.0
