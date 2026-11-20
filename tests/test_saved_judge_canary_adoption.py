import json,copy,hashlib
from pathlib import Path
import pytest
from tools import saved_judge_canary_adoption as m
from tools import run_new_package_matrix as driver

def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return {'path':str(p),'sha256':m.sha(p)}

@pytest.fixture
def bound(tmp_path,monkeypatch):
 root=tmp_path/'full/codex/matrix';output=root/'l2/frozen/codex/s12';cp=output/'_checkpoints/stream/run/p0002-02'
 row={'id':'l2/frozen/codex/s12','level':'l2','agent':'codex','condition':'frozen','output':str(output),'turns':['turn1','turn2','turn3','turn4'],'package':'package','stream':'stream','panel_id':'original-panel','panel_manifest_sha256':'original-panel-sha','selected_stream_ids':['stream'],'runtime_profiles_sha256':'original-runtime-sha'}
 put(cp/'checkpoint.json',{'phase':'adjudicate','next_turn_index':2,'turn_id':'turn3','interaction_index':2})
 reply={'text':'original paid answer','raw':{'usage':'unknown remains unknown'}}
 put(cp/'evidence.json',{'turn_id':'turn3','interaction_index':2,'reply':reply});put(cp/'completed_turns.json',[{'turn_id':'turn1','score':0},{'turn_id':'turn2','score':0}])
 put(cp/'workspace.zip',{'immutable':'workspace'});put(cp/'baseline_state.zip',{'immutable':'learner'})
 original=put(tmp_path/'config/tmp_codex_docker.override.json',{'model':'terra','options':{'max_model_calls':10,'judge_parse_attempts':2}})
 source=put(tmp_path/'source-auth.json',{'authorization':'original user quote'})
 inputauth=put(tmp_path/'input-auth.json',{'version':'1.1'})
 imap=put(tmp_path/'input-map.json',{'schema':'trievo_judge_input_map/1.1','targets':[{'condition':'frozen','turn_id':'turn3','interaction_index':2,'authorization':inputauth}]})
 fixeddata=json.loads(Path(original['path']).read_text());fixeddata['options']['l2_judge_shared_evidence_map']=imap
 fixed=put(tmp_path/'fixed/tmp_codex_docker.override.json',fixeddata)
 launch=put(tmp_path/'launch.json',{'command':['all mandatory maps retained']});parent=put(tmp_path/'parent.json',{'status':'previous claim retained'})
 report=put(output/'stream/run/report.json',{'error':'evaluation_error turn3 HTTP 502'})
 monkeypatch.setattr(driver,'completed_target_evidence',lambda *args:None)
 originalargs=driver.command(tmp_path,row,cp,tmp_path/'config')
 expected=driver.command(tmp_path,row,cp,tmp_path/'config',stop_after_turn='turn3');expected[expected.index('--baseline-config')+1]=fixed['path']
 g={'schema':'exact_shared_saved_judge_canary/1.1','scope_sha256':m.FORMAL_SHA,'job':row['id'],'condition':'frozen','stop_after_turn':'turn3','original_attempt_budgets_unchanged':True,'original_paid_reply_not_replayed':True,'all_original_costs_retained':True,'input_representation_and_stateful_descendants_review_pending':True,'frontier':{'job':row['id'],'checkpoint':str(cp),'turn_id':'turn3','interaction_index':2,'reply_sha256':hashlib.sha256(json.dumps(reply,sort_keys=True).encode()).hexdigest(),'report':report['path'],'report_sha256':report['sha256'],'checkpoint_sha256':{n:m.sha(cp/n) for n in ('checkpoint.json','evidence.json','completed_turns.json','workspace.zip','baseline_state.zip')}},'source_authorization':source,'original_config':original,'fixed_config':fixed,'input_map':imap,'full_launch_receipt':launch,'parent_claims':[parent],'native_command':expected}
 ref=put(tmp_path/'grant.json',g);row[m.FIELD]=ref
 return root,row,cp,g,originalargs,expected

def rewrite(row,g):row[m.FIELD]=put(Path(row[m.FIELD]['path']),g)

def test_exact_native_command_keeps_original_budgets_prefix_and_stop(bound):
 root,row,cp,g,args,expected=bound
 assert driver.command(root,row,cp,Path(g['original_config']['path']).parent)==expected
 assert m.bound_command(row,cp,args)==expected
 mapping=put(root.parent/'map.json',{'schema':'trievo.saved-judge-single-canary/1.0','entries':[{'job':row['id'],'authorization':row[m.FIELD]}]})
 before=copy.deepcopy(row);del before[m.FIELD]
 adopted=m.apply([before],root,Path(mapping['path']))
 assert adopted[0]['turns']==before['turns'] and m.FIELD in adopted[0] and m.FIELD not in before

@pytest.mark.parametrize('target',['workspace.zip','baseline_state.zip','completed_turns.json','checkpoint.json','evidence.json'])
def test_changed_exact_state_rejected(bound,target):
 _,row,cp,g,args,_=bound;(cp/target).write_bytes(b'changed')
 with pytest.raises(ValueError,match='state changed'):m.bound_command(row,cp,args)

@pytest.mark.parametrize('field',['source_authorization','original_config','fixed_config','input_map','full_launch_receipt'])
def test_changed_parent_or_config_rejected(bound,field):
 _,row,cp,g,args,_=bound;Path(g[field]['path']).write_bytes(b'changed')
 with pytest.raises(ValueError,match='binding changed'):m.bound_command(row,cp,args)

def test_budget_increase_rejected_even_when_fixed_config_digest_updated(bound):
 _,row,cp,g,args,_=bound;fixed=Path(g['fixed_config']['path']);d=json.loads(fixed.read_text());d['options']['max_model_calls']=11;g['fixed_config']=put(fixed,d);rewrite(row,g)
 with pytest.raises(ValueError,match='budgets/options'):m.bound_command(row,cp,args)

def test_completed_target_cannot_be_regraded(bound,monkeypatch):
 _,row,cp,g,args,_=bound;monkeypatch.setattr(driver,'completed_target_evidence',lambda *args:{'score':0})
 with pytest.raises(ValueError,match='already completed'):m.bound_command(row,cp,args)

def test_command_or_checkpoint_movement_rejected(bound):
 _,row,cp,g,args,_=bound
 with pytest.raises(ValueError,match='checkpoint moved'):m.bound_command(row,cp.parent,args)
 args=args.copy();args[args.index('--max-total-tokens')+1]='999999999999'
 with pytest.raises(ValueError,match='budget changed'):m.bound_command(row,cp,args)

def test_normal_jobs_keep_identical_command(bound):
 _,row,cp,g,args,_=bound;del row[m.FIELD];assert m.bound_command(row,cp,args) is args

def test_bounded_completion_preserves_full_scope_and_normal_zero(bound,monkeypatch):
 _,row,cp,g,args,_=bound;seen=[]
 def report(r,turn):
  seen.append((r['turns'][:],turn));return Path('bounded-report.json'),{'stopped_after_turn':turn,'turns':[{'turn_id':'turn3','score':0,'passed':False}]}
 monkeypatch.setattr(driver,'report_for_interrupted_retry',report)
 path,result=m.finished_report(row)
 assert seen==[(['turn1','turn2','turn3','turn4'],'turn3')]
 assert result['turns'][0]['score']==0 and len(row['turns'])==4

def test_changed_completed_grant_is_review_error_without_crashing_other_paid_workers(bound):
 _,row,cp,g,args,_=bound;Path(row[m.FIELD]['path']).write_text('changed')
 assert m.finished_report(row)==(None,None) and 'grant changed' in row['saved_judge_canary_review_error']

@pytest.mark.parametrize('status',[None,'pending','running','needs_attention','paused_error'])
def test_width_adoption_preserves_contract_when_old_launch_command_has_no_new_flag(bound,status):
 _,row,cp,g,args,expected=bound;prior=copy.deepcopy(row);prior['status']=status
 current=copy.deepcopy(row);del current[m.FIELD]
 driver.restore_adoption_boundaries([current],{'jobs':[prior]})
 assert current[m.FIELD]==row[m.FIELD]
 assert m.bound_command(current,cp,args)==expected

def test_width_adoption_rejects_changed_reference_without_replaying_paid_answer(bound):
 _,row,cp,g,args,_=bound;prior=copy.deepcopy(row);Path(prior[m.FIELD]['path']).write_text('changed')
 with pytest.raises(ValueError,match='authorization changed'):driver.restore_adoption_boundaries([row],{'jobs':[prior]})

@pytest.mark.parametrize('key,value',[('condition','reset'),('stop_after_turn','turn4'),('original_paid_reply_not_replayed',False)])
def test_scope_or_stop_or_replay_change_rejected(bound,key,value):
 _,row,cp,g,args,_=bound;g[key]=value;rewrite(row,g)
 with pytest.raises(ValueError,match='single-target'):m.bound_command(row,cp,args)
