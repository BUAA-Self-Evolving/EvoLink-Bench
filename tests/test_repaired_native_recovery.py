import copy
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from evolink_bench.repaired_native_recovery import sha, validate, reuse

@pytest.fixture
def case(tmp_path):
 def put(name,data):
  p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data));return {'path':str(p),'sha256':sha(p)}
 task={'turn_id':'turn7','stream_id':'stream'}
 evidence={'turn_id':'turn7','interaction_index':1,'history':[],'interactions':[],'request':'request','reply':{'text':'paid','tool_calls':[],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2,'api_calls':1}}}
 cp=tmp_path/'cp';cp.mkdir();m={'phase':'adjudicate','baseline':'codex','condition':'reset','turn_id':'turn7','interaction_index':1,'next_turn_index':6,'token_budget':{'limit':100,'used':20,'calls':19}}
 for name,data in [('checkpoint.json',m),('evidence.json',evidence),('completed_turns.json',[])]: (cp/name).write_text(json.dumps(data))
 for name in ['workspace.zip','baseline_state.zip']:(cp/name).write_bytes(b'original')
 hashes={p.name:sha(p) for p in cp.iterdir()};trace=tmp_path/'trace.jsonl';trace.write_text(json.dumps({'turn_id':'turn7','interaction_index':1,'request':'request','response':'paid','tool_calls':[],'verifier':{'native_result':{'private_diagnostics':{'reason':'invalid_submission','error':"[Errno 13] Permission denied: '/workspace/x'"}}}}))
 taskref=put('task.json',task);parent=put('ledger.json',{'status':'consumed'})
 proof={'job':'l2/reset/codex/s22','source_checkpoint':str(cp),'source_checkpoint_sha256':hashes,'source_task_sha256':taskref['sha256'],'original_saved_reply_exactly_matches_source_trace':True,'original_bf5e_reply_workspace_equal':True,'original_archives_and_workspace_unchanged':True,'network_none_observed':True,'agent_replays':0,'judge_calls':0,'learning_calls':0,'production_claims':0,'native_verifier_containers':1,'cleanup_actual_inspect':{'container':{'absent':True}},'original_trace':{'path':str(trace),'sha256':sha(trace)},'native_result':{'native_result':{'status':'pass','score':0.8}}}
 a={'schema':'trievo.uncommitted-reset-permission-recovery.v1','job':'l2/reset/codex/s22','stream_key':'s22','baseline':'codex','condition':'reset','turn':'turn7','interaction':1,'agent_replays':0,'select_by_score':False,'all_original_costs_retained':True,'unknown_historical_usage':True,'checkpoint':str(cp),'checkpoint_sha256':hashes,'projection':put('projection.json',{'placements':[{'job':'l2/reset/codex/s22','turn':f'turn{i}'} for i in range(1,7)]}),'user_authorization':put('user.json',{'extra_recovery_spend_authorized':True,'valid_low_score_reruns_authorized':False}),'parent_claims':put('parents.json',{'claims':[parent]}),'native_proof':put('proof.json',proof),'task':taskref,'historical_accounting':put('accounting.json',{'unique_historical_known_token_lower_bound':25,'unique_historical_known_call_lower_bound':23,'unknown_later_failed_judge_tokens':True,'current_59826747_failure_usage_not_included_as_zero':True}),'historical_known_lower_bound':{'used':25,'calls':23},'token_limit':100,'workspace_inventory':{'x':'sha'}}
 return a,cp,put,task,evidence

def check(case,a=None,**kw):
 original,cp,put,_,_=case;ref=put('authority.json',a or original)
 return validate(ref,checkpoint=cp,baseline='codex',condition='reset',stop_after_turn='turn7',**kw)

def test_exact_case_accepts_with_unknown_costs_preserved(case):
 assert check(case)['historical_known_lower_bound']['calls']==23

@pytest.mark.parametrize('field,value',[('agent_replays',1),('select_by_score',True),('unknown_historical_usage',False),('token_limit',101),('historical_known_lower_bound',{'used':20,'calls':19}),('condition','frozen')])
def test_invalid_authority_rejected(case,field,value):
 a=copy.deepcopy(case[0]);a[field]=value
 with pytest.raises(ValueError):check(case,a)

def test_completed_target_cannot_be_regraded(case):
 a,_,put,_,_=case;a=copy.deepcopy(a);a['projection']=put('recorded.json',{'placements':[{'job':a['job'],'turn':f'turn{i}'} for i in range(1,8)]})
 with pytest.raises(ValueError,match='already recorded'):check(case,a)

def test_original_checkpoint_mutation_rejected(case):
 (case[1]/'workspace.zip').write_bytes(b'changed')
 with pytest.raises(ValueError,match='checkpoint changed'):check(case)

def test_native_proof_changed_rejected(case):
 Path(case[0]['native_proof']['path']).write_text('{}')
 with pytest.raises(ValueError,match='evidence changed'):check(case)

def test_parent_claim_mutation_rejected(case):
 (case[1].parent/'ledger.json').write_text('{}')
 with pytest.raises(ValueError,match='claim changed'):check(case)

def test_reuse_checks_paid_reply_and_workspace(case):
 a,cp,put,task,e=case;ref=put('authority.json',a);reply=SimpleNamespace(text='paid',tool_calls=[],usage=SimpleNamespace(to_dict=lambda:e['reply']['usage']))
 out=reuse(ref,checkpoint=cp,baseline='codex',condition='reset',stop_after_turn='turn7',task=task,reply=reply,workspace_inventory=a['workspace_inventory'])
 assert out['native_result']['status']=='pass'
 with pytest.raises(ValueError,match='differs'):reuse(ref,checkpoint=cp,baseline='codex',condition='reset',stop_after_turn='turn7',task=task,reply=reply,workspace_inventory={})
