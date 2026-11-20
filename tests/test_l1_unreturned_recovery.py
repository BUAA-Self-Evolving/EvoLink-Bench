import hashlib,json,sys,zipfile
from pathlib import Path
import pytest
from tools import l1_unreturned_recovery as v

def fixture(tmp_path):
 out=tmp_path/'job';flow=out/'stream';flow.mkdir(parents=True)
 package=tmp_path/'package';package.mkdir();(package/'manifest.json').write_text('{}')
 row=dict(id='l1/evolving/hermes/s02',level='l1',condition='evolving',agent='hermes',
          flow_id='stream',stream='stream-2',turns=['t1','t2','t3'],output=str(out),package=str(package),status='paused_error')
 cp=out/'_checkpoints'/hashlib.sha256(b'stream').hexdigest()[:10]/'t0001';cp.mkdir(parents=True)
 (cp/'checkpoint.json').write_text(json.dumps(dict(flow_id='stream',baseline='hermes',condition='evolving',next_turn_index=1,exact_baseline_state=True)))
 (cp/'completed_turns.json').write_text(json.dumps([dict(turn_id='t1',score=0,passed=False)]))
 for name in ['workspace.zip','baseline_state.zip']:
  with zipfile.ZipFile(cp/name,'w'):pass
 record=dict(turn_id='t2',index=1,response='',actions=[],tool_calls=[],events=[],state_update={},verifier_details=dict(type='model_error',error='baseline adapter timed out during interact'))
 trace=flow/'live_trace.jsonl';trace.write_text(json.dumps(record)+'\n')
 log=out/'driver-1.log';log.write_text('RuntimeError: evaluation infrastructure failed in t2: Model request failed: baseline adapter timed out during interact', encoding='utf-8')
 return row,record,trace,cp,log

def test_valid_low_prefix_and_unknown_failed_usage_preserved(tmp_path):
 row,_,_,cp,_=fixture(tmp_path);proof=v.inspect_frontier(row)
 assert proof['turn_id']=='t2' and proof['preserve_valid_turns']==['t1']
 assert proof['checkpoint']==str(cp)
 assert proof['failed_usage'].startswith('unknown')
 v.validate_bindings(proof)

@pytest.mark.parametrize('change',['reply','tool','later_interaction','earlier_paid_reply','evolve','policy','foreign_turn','wrong_condition','checkpoint_exists','missing_log','inexact_state'])
def test_unsafe_paid_or_unbound_frontiers_fail_closed(tmp_path,change):
 row,record,trace,cp,log=fixture(tmp_path)
 if change=='reply':record['response']='already paid'
 if change=='tool':record['tool_calls']=[{'already_executed':True}]
 if change=='later_interaction':record['index']=2
 if change=='evolve':record['verifier_details']['error']='baseline adapter timed out during evolve'
 if change=='policy':record['verifier_details']['error']='HTTP 403: content_policy_violation'
 if change=='foreign_turn':record['turn_id']='t3'
 if change=='wrong_condition':row['condition']='frozen'
 if change=='checkpoint_exists':(cp.parent/'t0002').mkdir()
 if change=='missing_log':log.unlink()
 if change=='inexact_state':
  d=json.loads((cp/'checkpoint.json').read_text());d['exact_baseline_state']=False;(cp/'checkpoint.json').write_text(json.dumps(d))
 trace.write_text(json.dumps(record)+'\n')
 if change=='earlier_paid_reply':trace.write_text(json.dumps({**record,'response':'valid reply'})+'\n'+json.dumps(record)+'\n')
 with pytest.raises((ValueError,OSError)):v.inspect_frontier(row)

def test_command_is_bounded_to_prefix_plus_one_unfinished_turn(tmp_path,monkeypatch):
 row,_,_,_,_=fixture(tmp_path);proof=v.inspect_frontier(row)
 seen=[]
 def command(repo,partial,cp,config):
  seen.append(partial);return ['python','-m','evolink_bench.l1_arena_compat','--turns',','.join(partial['turns'])]
 monkeypatch.setattr(v,'command',command)
 argv,partial=v.bounded_command(tmp_path,row,tmp_path/'branch',None,tmp_path,proof)
 assert partial['turns']==['t1','t2'] and row['turns']==['t1','t2','t3']
 assert partial['package']==row['package'] and partial['condition']==row['condition']
 assert argv[-1]=='t1,t2'
 assert seen[0]['turns']==row['turns']  # original aggregate fuse, unchanged

@pytest.mark.skipif(sys.platform!='linux',reason='ledger uses server flock')
def test_evidence_change_does_not_consume_and_second_attempt_is_forbidden(tmp_path):
 row,_,trace,_,_=fixture(tmp_path);proof=v.inspect_frontier(row)
 p=tmp_path/'auth.json';p.write_text(json.dumps(dict(status='authorized_not_consumed',allowed_additional_attempts=1,proof=proof)))
 original=trace.read_text();trace.write_text(original+'\n')
 with pytest.raises(ValueError,match='bound evidence changed'):v.consume_authorization(p,proof,['bounded'])
 assert json.loads(p.read_text())['status']=='authorized_not_consumed'
 trace.write_text(original);v.consume_authorization(p,proof,['bounded'])
 assert json.loads(p.read_text())['status']=='consumed'
 with pytest.raises(ValueError,match='already consumed'):v.consume_authorization(p,proof,['bounded'])

@pytest.mark.parametrize('error',['Error code: 502 - ConnectError','Error code: 504 - upstream transport timed out','Error code: 502 - 本次请求出现异常，请稍后重试。'])
def test_service_error_recovery_remains_bound_to_no_reply_and_driver(tmp_path,error):
 row,record,trace,cp,log=fixture(tmp_path);record['verifier_details']['error']=error;trace.write_text(json.dumps(record)+'\n');log.write_text('evaluation infrastructure failed in t2: '+error, encoding='utf-8')
 assert v.inspect_frontier(row)['prefix_count']==1
 record['response']='paid';trace.write_text(json.dumps(record)+'\n')
 with pytest.raises(ValueError):v.inspect_frontier(row)
