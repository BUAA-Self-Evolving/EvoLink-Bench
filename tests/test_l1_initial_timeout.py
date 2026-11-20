from pathlib import Path
import copy,json,zipfile,hashlib
import pytest
from tools import l1_initial_timeout as m

def put(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
def bundle(p,d):
 p.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(p,'w') as z:
  for n,b in d.items():z.writestr(n,b)

@pytest.fixture
def sample(tmp_path):
 out=tmp_path/'original';flow=out/'flow';failed=flow/'failed_evolution/abc'
 row={'id':'l1/evolving/adaptive-auto-harness/s16','level':'l1','condition':'evolving','agent':'adaptive-auto-harness','status':'paused_error','output':str(out),'flow_id':'flow','turns':['turn1','turn2'],'log':str(out/'driver.log')}
 bundle(failed/'baseline_state.zip',{'memory/m.json':'original'})
 snap=m.snapshot_from_checkpoint(failed/'baseline_state.zip');put(failed/'baseline_state_snapshot.json',snap);put(failed/'failure.json',{'turn_id':'turn1','state_digest':snap['digest'],'recoverable_checkpoint':False})
 work=tmp_path/'restored';work.mkdir();(work/'answer').write_bytes(b'answer')
 target=[{'path':'/workspace/answer','size':6,'sha256':hashlib.sha256(b'answer').hexdigest()}]
 record={'turn_id':'turn1','index':1,'request':'q','response':'original paid answer','score':1.0,'passed':True,'action_error':None,'verifier_details':{},'state_before':snap['state'],'sandbox':{'files':target},'usage':{'total_tokens':14087,'api_calls':3}}
 (flow/'live_trace.jsonl').write_text(json.dumps(record)+'\n');Path(row['log']).write_text(m.ERROR+'\n')
 review=tmp_path/'restoration.json';put(review,{'results':[{'job':row['id'],'file_count':1,'exact_original_post_answer_snapshot_restored':True}]})
 auth=tmp_path/'authority.json';put(auth,{'schema':m.SCHEMA,'job':row['id'],'policy':'independent_initial_timeout_original_paid_answer_preserved','failed_learning_usage':'unknown','additional_learning_attempts':0,'original_native_budget_receipt_claimed':False,'post_failure_exact_continuation_claimed':False,'aggregate_policy':'separate_conservative_public_cli_default_fuse','independent_fuse':3000000})
 source=tmp_path/'cli.py';source.write_text("parser.add_argument('--max-total-tokens',type=int,default=3_000_000)\n")
 return row,review,work,auth,source

def test_initial_recovery_keeps_paid_answer_unknown_cost_and_separate_fuse(sample,tmp_path):
 proof,pending=m.inspect(*sample);assert proof['derived_known_budget_lower_bound']=={'limit':3000000,'used':14087,'calls':3}
 assert proof['original_aggregate_ceiling']=='unknown_missing_native_cli_receipt'
 result=m.materialize(sample[0],(proof,pending),tmp_path/'independent');cp=Path(result['checkpoint']);records=m.load(cp/'completed_turns.json');assert records[0]['score']==1 and records[0]['evolution']['completed'] is False
 meta=m.load(cp/'checkpoint.json');assert meta['independent_recovery']['original_native_checkpoint_claimed'] is False
 assert meta['independent_recovery']['original_aggregate_ceiling_claimed'] is False
 from tools.audit_matrix_scores import learning_tags,transcript_check,TraceReader
 assert learning_tags(records[0])['derived_bounded_failure'] is True
 assert transcript_check(sample[0],records[0],cp/'completed_turns.json',TraceReader())['verified'] is True
 with pytest.raises(ValueError,match='already exists'):m.materialize(sample[0],(proof,pending),tmp_path/'independent')

@pytest.mark.parametrize('key,value',[('original_native_budget_receipt_claimed',True),('failed_learning_usage','zero'),('additional_learning_attempts',1),('independent_fuse',180000000),('post_failure_exact_continuation_claimed',True)])
def test_does_not_upgrade_unknown_original_authority(sample,key,value):
 d=m.load(sample[3]);d[key]=value;put(sample[3],d)
 with pytest.raises(ValueError):m.inspect(*sample)

def test_changed_learner_is_rejected(sample):
 p=Path(sample[0]['output'])/'flow/failed_evolution/abc/baseline_state.zip';bundle(p,{'memory/m.json':'changed'})
 with pytest.raises(ValueError,match='learner changed'):m.inspect(*sample)

def test_incomplete_task_is_rejected(sample):
 (sample[2]/'answer').unlink()
 with pytest.raises(ValueError,match='task bytes'):m.inspect(*sample)

def test_other_or_later_paid_history_rejected(sample):
 p=Path(sample[0]['output'])/'flow/live_trace.jsonl';d=json.loads(p.read_text());d['turn_id']='turn2';p.write_text(p.read_text()+json.dumps(d)+'\n')
 with pytest.raises(ValueError,match='paid history'):m.inspect(*sample)

def test_forged_budget_is_rejected_before_output(sample,tmp_path):
 inspection=m.inspect(*sample);inspection[0]['derived_known_budget_lower_bound']['calls']=0
 with pytest.raises(ValueError,match='forged'):m.materialize(sample[0],inspection,tmp_path/'bad')
 assert not (tmp_path/'bad').exists()

def test_initial_recovery_cannot_take_live_owner(sample):
 sample[0]['status']='running'
 with pytest.raises(ValueError,match='unowned'):m.inspect(*sample)

def test_source_default_cannot_silently_change(sample):
 sample[4].write_text("parser.add_argument('--max-total-tokens',default=180_000_000)\n")
 with pytest.raises(ValueError,match='conservative'):m.inspect(*sample)
