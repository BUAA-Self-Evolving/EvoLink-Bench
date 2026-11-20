from pathlib import Path
import hashlib,json,zipfile
import pytest
from tools import finalize_l2_evolution_timeout as v

def put(path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data))
def archive(path,files):
 with zipfile.ZipFile(path,'w') as z:
  for name,value in files.items():z.writestr(name,value)

def fixture(tmp):
 output=tmp/'original';run=output/'stream/failed';run.mkdir(parents=True)
 row=dict(level='l2',id='l2/evolving/hermes/s01',agent='hermes',flow_id='stream',condition='evolving',turns=['t1','t2','t3'],turn_roles={'t2':'learning'},output=str(output),status='paused_error')
 prefix=[dict(turn_id='t1',condition='evolving',turn_score=0,passed=False,evaluation_status='failed',final_category='fail')]
 cp=output/'_checkpoints/key/failed/p0001-01';cp.mkdir(parents=True)
 archive(cp/'baseline_state.zip',{'memory.md':'learned previous memory','.trievo_semantic_state.json':'{}'})
 archive(cp/'workspace.zip',{'artifact.txt':'paid final artifact'})
 archive(run/'error_workspace.zip',{'artifact.txt':'paid final artifact'})
 meta=dict(phase='adjudicate',run_id='failed',stream_id='stream',baseline='hermes',condition='evolving',next_turn_index=1,turn_id='t2',interaction_index=1,learner_state_digest=v.sha(cp/'baseline_state.zip'))
 put(cp/'checkpoint.json',meta);put(cp/'completed_turns.json',prefix)
 final=dict(turn_id='t2',interaction_index=1,request='original',response='paid original reply',tool_calls=[],score=.9,passed=True,evaluation_status='passed',verifier={'category':'pass'})
 put(cp/'evidence.json',dict(request='original',reply={'text':'paid original reply','tool_calls':[]},interactions=[]))
 (run/'trace.jsonl').write_text(json.dumps(final)+'\n')
 put(run/'failed_evolution/export/failure.json',{'turn_id':'t2','recoverable_checkpoint':False})
 report=dict(run_id='failed',stream_id='stream',baseline='hermes',condition='evolving',turns=prefix,error=v.ERROR,finished_at='original-finish',token_budget={'limit':10000000,'used':300,'calls':4},run_configuration={'budget_profile':'formal','effective_work_limits':{'evolution_timeout_seconds':120},'execution_requirements':{'max_interactions':3}})
 put(run/'report.json',report)
 return row,run,cp,report,final

def test_preserves_agent_score_but_learning_remains_failed_and_unknown_usage(tmp_path):
 row,run,cp,_,_=fixture(tmp_path);inspection=v.inspect_timeout(row,run/'report.json')
 old={str(p):p.read_bytes() for p in row_path(row).rglob('*') if p.is_file()}
 result=v.materialize(row,inspection,tmp_path/'recovery')
 report=json.loads(Path(result['report']).read_text());turn=report['turns'][-1]
 assert turn['turn_score']==.9 and turn['passed'] is False and turn['final_category']=='evolution_limit'
 assert turn['evolution']['completed'] is False
 assert turn['evolution']['state_before']==turn['evolution']['state_after']
 assert turn['evolution']['usage']=={} and turn['evolution']['usage_status']=='unknown_failed_evolution'
 assert result['additional_model_calls']==0
 assert report['token_budget']==inspection[1]['token_budget']
 assert Path(result['checkpoint'],'baseline_state.zip').read_bytes()==(cp/'baseline_state.zip').read_bytes()
 assert old=={str(p):p.read_bytes() for p in row_path(row).rglob('*') if p.is_file()}

def row_path(row):return Path(row['output'])

@pytest.mark.parametrize('change',['hold','budget','wrong_error','incomplete_history','mismatched_reply','evaluator_error','workspace_change','completed_evolve','missing_export','wrong_prefix','archive_digest','nonterminal','foreign_condition','duplicate_terminal'])
def test_unsafe_or_ambiguous_learning_frontiers_are_never_finalized(tmp_path,change):
 row,run,cp,report,final=fixture(tmp_path)
 if change=='hold':put(row_path(row)/'_learning_continuity_hold.json',{'status':'unresolved','valid_prefix_turns':1})
 if change=='budget':report['run_configuration']['effective_work_limits']['evolution_timeout_seconds']=300
 if change=='wrong_error':report['error']='HTTP 502'
 if change=='incomplete_history':
  meta=json.loads((cp/'checkpoint.json').read_text());meta['interaction_index']=2;put(cp/'checkpoint.json',meta);final['interaction_index']=2
 if change=='mismatched_reply':final['response']='different reply'
 if change=='evaluator_error':final['evaluation_status']='evaluation_error'
 if change=='workspace_change':archive(run/'error_workspace.zip',{'artifact.txt':'changed later'})
 if change=='missing_export':(run/'failed_evolution/export/failure.json').unlink()
 if change=='wrong_prefix':report['turns'][0]['turn_id']='different'
 if change=='archive_digest':archive(cp/'baseline_state.zip',{'memory.md':'tampered'})
 if change=='nonterminal':final.update(passed=False,score=.2,verifier={'category':'fail'})
 if change=='foreign_condition':report['condition']='frozen'
 put(run/'report.json',report);(run/'trace.jsonl').write_text(json.dumps(final)+'\n')
 if change=='completed_evolve':
  with (run/'trace.jsonl').open('a') as f:f.write(json.dumps({'turn_id':'t2','record_type':'evolution','evolution':{'completed':True}})+'\n')
 if change=='duplicate_terminal':
  with (run/'trace.jsonl').open('a') as f:f.write(json.dumps(final)+'\n')
 with pytest.raises((ValueError,OSError)):v.inspect_timeout(row,run/'report.json')

def test_changed_bound_evidence_is_rejected_before_new_artifacts(tmp_path):
 row,run,_,_,_=fixture(tmp_path);inspection=v.inspect_timeout(row,run/'report.json')
 with (run/'trace.jsonl').open('a') as f:f.write('\n')
 with pytest.raises(ValueError,match='bound evidence changed'):v.materialize(row,inspection,tmp_path/'recovery')
 assert not (tmp_path/'recovery').exists()

def test_unsafe_archive_cannot_be_used_as_a_restored_learning_state(tmp_path):
 p=tmp_path/'bad.zip';archive(p,{'../escape':'bad'})
 with pytest.raises(ValueError,match='unsafe'):v.archive_inventory(p)
