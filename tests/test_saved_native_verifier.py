from pathlib import Path
from types import SimpleNamespace
import copy,json,hashlib
import pytest
from evolink_bench import saved_native_verifier as m
from evolink_bench.baselines.base import UsageDetails

def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return {'path':str(p),'sha256':m.sha(p)}
@pytest.fixture
def saved(tmp_path):
 source=tmp_path/'source';cp=tmp_path/'resume';usage=UsageDetails().to_dict()
 evidence={'turn_id':'turn3','interaction_index':2,'reply':{'text':'paid','tool_calls':[],'usage':usage},'history':[{'role':'user','content':'original conversation'}],'interactions':[{'different':'record'}]}
 meta={'phase':'adjudicate','turn_id':'turn3','interaction_index':2,'token_budget':{'remaining':13}}
 for directory in (source,cp):
  for n,v in [('evidence.json',evidence),('checkpoint.json',meta),('completed_turns.json',[{'turn_id':'turn1','score':0}]),('workspace.zip',{'exact':'artifact'}),('baseline_state.zip',{'exact':'learner'})]:put(directory/n,v)
 task={'stream_id':'stream','turn_id':'turn3'};verification={'category':'pass','score':1,'native_result':{'private_diagnostics':{'duration_ms':17,'stdout_tail':'complete original output'},'metric':1},'judge_error':{'error':'old 502'}}
 trace=put(tmp_path/'trace.jsonl',{'turn_id':'turn3','interaction_index':2,'response':'paid','tool_calls':[],'verifier':verification})
 g={'schema':'trievo.saved-native-verifier/1.0','baseline':'codex','condition':'frozen',**task,'interaction_index':2,'checkpoint':str(cp),'source_checkpoint':str(source),'checkpoint_sha256':{p.name:m.sha(p) for p in cp.iterdir()},'source_checkpoint_sha256':{p.name:m.sha(p) for p in source.iterdir()},'verification':verification,'source_trace':trace,'workspace_inventory':{'file':'sha'},'source_authorization':put(tmp_path/'user.json',{'authorized':True}),'task':put(tmp_path/'task.json',task),'equivalence_audit':put(tmp_path/'equivalence.json',{'source_checkpoint':str(source),'checkpoint':str(cp),'workspace_and_learner_equal':True,'remaining_budget_equal':True})}
 ref=put(tmp_path/'binding.json',g)
 args={'checkpoint':cp,'baseline':'codex','condition':'frozen','task':task,'reply':SimpleNamespace(text='paid',tool_calls=[],usage=UsageDetails()),'workspace_inventory':{'file':'sha'}}
 return ref,g,args

def test_full_native_diagnostics_retained_and_zero_score_not_retried(saved):
 ref,g,args=saved;result=m.reuse(ref,**args)
 assert result['native_result']==g['verification']['native_result']
 assert 'judge_error' not in result and result['saved_native_verifier_provenance']['source_judge_error']==g['verification']['judge_error']
 assert result['saved_native_verifier_provenance']['agent_replays']==0
 result['native_result']['metric']=0
 assert g['verification']['native_result']['metric']==1

@pytest.mark.parametrize('field',['baseline','condition','checkpoint','workspace_inventory','task','reply'])
def test_actual_target_reply_artifact_rejected(saved,field):
 ref,g,args=saved
 if field=='reply':args[field]=SimpleNamespace(text='new answer',tool_calls=[],usage=UsageDetails())
 elif field=='task':args[field]={**args[field],'turn_id':'turn4'}
 elif field=='workspace_inventory':args[field]={'file':'changed'}
 else:args[field]='changed'
 with pytest.raises((ValueError,KeyError)):m.reuse(ref,**args)

@pytest.mark.parametrize('field',['source_trace','task','source_authorization','equivalence_audit'])
def test_evidence_digest_changes_rejected(saved,field):
 ref,g,args=saved;Path(g[field]['path']).write_text('{}')
 with pytest.raises(ValueError):m.reuse(ref,**args)

@pytest.mark.parametrize('name',['evidence.json','checkpoint.json','completed_turns.json','workspace.zip','baseline_state.zip'])
def test_source_or_resumed_state_changes_rejected(saved,name):
 ref,g,args=saved;(Path(g['checkpoint'])/name).write_text('{}')
 with pytest.raises(ValueError,match='state changed'):m.reuse(ref,**args)

def test_rebound_budget_change_still_rejected(saved):
 ref,g,args=saved;p=Path(g['checkpoint'])/'checkpoint.json';v=json.loads(p.read_text());v['token_budget']['remaining']=100;put(p,v);g['checkpoint_sha256'][p.name]=m.sha(p);ref=put(Path(ref['path']),g)
 with pytest.raises(ValueError,match='budget differs'):m.reuse(ref,**args)

def test_ambiguous_original_trace_cannot_be_selected(saved):
 ref,g,args=saved;p=Path(g['source_trace']['path']);p.write_text(p.read_text()+'\n'+p.read_text());g['source_trace']['sha256']=m.sha(p);ref=put(Path(ref['path']),g)
 with pytest.raises(ValueError,match='ambiguous'):m.reuse(ref,**args)

def test_only_adjudicate_resume_may_use_feature(saved,monkeypatch,tmp_path):
 from evolink_bench.l2_agent import L2AgentStreamRunner
 from evolink_bench import l2_agent
 ref,g,args=saved;fake=SimpleNamespace(options=SimpleNamespace(baseline='codex',baseline_overrides={'options':{'l2_saved_native_verifier':ref}}),condition=SimpleNamespace(value='frozen'))
 with pytest.raises(RuntimeError,match='exact adjudication'):L2AgentStreamRunner._verify_taskstream(fake,task=args['task'],turn_dir=tmp_path,workspace=tmp_path,reply=args['reply'])
 fake._saved_native_adjudicate_checkpoint=args['checkpoint'];monkeypatch.setattr(l2_agent,'_workspace_digest',lambda _:args['workspace_inventory'])
 result=L2AgentStreamRunner._verify_taskstream(fake,task=args['task'],turn_dir=tmp_path,workspace=tmp_path,reply=args['reply'])
 assert result['native_result']==g['verification']['native_result'] and fake._saved_native_adjudicate_checkpoint is None
 fake._verify_taskstream_in_volume=lambda **_: {'native_result':{'metric':0},'category':'fail'}
 later=L2AgentStreamRunner._verify_taskstream(fake,task=args['task'],turn_dir=tmp_path,workspace=tmp_path,reply=args['reply'])
 assert later=={'native_result':{'metric':0},'category':'fail'}
