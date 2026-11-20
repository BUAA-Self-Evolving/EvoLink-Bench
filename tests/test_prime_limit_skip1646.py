from pathlib import Path
import json
import pytest
from test_finalize_l2_evolution_timeout import fixture,put,archive
from tools import finalize_l2_evolution_timeout as v

def reviewed(tmp):
 row,run,cp,report,final=fixture(tmp)
 row.update(agent='prime-agent',id='l2/evolving/prime-agent/s14')
 report['baseline']='prime-agent';final.update(score=0,passed=False,verifier={'category':'execution_limit','details':{'type':'work_limit','reason':'max_tool_calls'}})
 put(run/'report.json',report);(run/'trace.jsonl').write_text(json.dumps(final)+'\n')
 meta=json.loads((cp/'checkpoint.json').read_text());meta.update(baseline='prime-agent',token_budget=report['token_budget']);put(cp/'checkpoint.json',meta)
 archive(run/'error_workspace.zip',{'artifact.txt':'actual post-timeout bytes','new.txt':'failed learning task side effect'})
 export=run/'failed_evolution/export';archive(export/'baseline_state.zip',{'memory.md':'failed learning never adopted'});put(export/'baseline_state_snapshot.json',{'failed':True})
 auth=tmp/'auth.json';put(auth,{'user_statement':'合法预算耗尽就当作失败，跳过当前turn就行','jobs':[row['id']]})
 review=tmp/'review.json';put(review,{'policy':'prime_exhausted_turn_preserve_failed_task_workspace','authorization':str(auth),'authorization_sha256':v.sha(auth),
 'job':row['id'],'report_sha256':v.sha(run/'report.json'),'checkpoint_sha256':v.sha(cp/'checkpoint.json'),'task_workspace_sha256':v.sha(run/'error_workspace.zip'),'learner_state_sha256':v.sha(cp/'baseline_state.zip'),'failure_sha256':v.sha(export/'failure.json')})
 return row,run,cp,review,auth

def test_keeps_actual_task_bytes_rollback_only_learning_no_replays(tmp_path):
 row,run,cp,review,_=reviewed(tmp_path)
 with pytest.raises(ValueError,match='workspace changed'):v.inspect_timeout(row,run/'report.json')
 original={str(p):p.read_bytes() for p in Path(row['output']).rglob('*') if p.is_file()}
 inspected=v.inspect_timeout(row,run/'report.json',failed_workspace_review=review)
 result=v.materialize(row,inspected,tmp_path/'derived');out=Path(result['checkpoint'])
 assert (out/'workspace.zip').read_bytes()==(run/'error_workspace.zip').read_bytes()
 assert (out/'baseline_state.zip').read_bytes()==(cp/'baseline_state.zip').read_bytes()
 report=json.loads(Path(result['report']).read_text());turn=report['turns'][-1]
 assert turn['turn_score']==0 and turn['passed'] is False and turn['evolution']['completed'] is False
 assert report['token_budget']==inspected[1]['token_budget']
 assert turn['evolution']['usage_status']=='unknown_failed_evolution'
 assert original=={str(p):p.read_bytes() for p in Path(row['output']).rglob('*') if p.is_file()}
 assert result['additional_model_calls']==0

@pytest.mark.parametrize('case',['other_agent','wrong_authorization','changed_authorization','foreign_report','changed_workspace','changed_learner','changed_failure','budget_mismatch','not_execution_limit','valid_pass','missing_export','invalid_archive'])
def test_declines_unbound_or_valid_work_and_keeps_default_guard(tmp_path,case):
 row,run,cp,review,auth=reviewed(tmp_path)
 if case=='other_agent':row['agent']='hermes'
 if case=='wrong_authorization':
  put(auth,{'user_statement':'do something else','jobs':[row['id']]});d=json.loads(review.read_text());d['authorization_sha256']=v.sha(auth);put(review,d)
 if case=='changed_authorization':put(auth,{'changed':True})
 if case=='foreign_report':d=json.loads(review.read_text());d['report_sha256']='0'*64;put(review,d)
 if case=='changed_workspace':archive(run/'error_workspace.zip',{'artifact.txt':'tampered'})
 if case=='changed_learner':archive(cp/'baseline_state.zip',{'memory.md':'tampered'})
 if case=='changed_failure':put(run/'failed_evolution/export/failure.json',{'changed':True})
 if case=='budget_mismatch':
  d=json.loads(cp.joinpath('checkpoint.json').read_text());d['token_budget']['used']+=1;put(cp/'checkpoint.json',d);d=json.loads(review.read_text());d['checkpoint_sha256']=v.sha(cp/'checkpoint.json');put(review,d)
 if case in ('not_execution_limit','valid_pass'):
  d=json.loads((run/'trace.jsonl').read_text());d['verifier']={'category':'fail'}
  if case=='valid_pass':d.update(score=1,passed=True)
  (run/'trace.jsonl').write_text(json.dumps(d)+'\n')
 if case=='missing_export':(run/'failed_evolution/export/baseline_state.zip').unlink()
 if case=='invalid_archive':archive(run/'failed_evolution/export/baseline_state.zip',{'../escape':'unsafe'})
 with pytest.raises((ValueError,OSError,KeyError)):
  v.inspect_timeout(row,run/'report.json',failed_workspace_review=review)

def test_workspace_changes_after_review_rejected_before_publication(tmp_path):
 row,run,_,review,_=reviewed(tmp_path);inspected=v.inspect_timeout(row,run/'report.json',failed_workspace_review=review)
 archive(run/'error_workspace.zip',{'artifact.txt':'changed after review'})
 with pytest.raises(ValueError,match='bound evidence changed'):v.materialize(row,inspected,tmp_path/'never-created')
 assert not (tmp_path/'never-created').exists()
