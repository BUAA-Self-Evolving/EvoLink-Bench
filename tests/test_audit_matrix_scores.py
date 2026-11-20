from pathlib import Path
import copy,json
import pytest
from tools import audit_matrix_scores as a

def put(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
def turn(t,score):return {'turn_id':t,'score':score,'passed':score==1,'interactions':[{'index':1,'score':score,'passed':score==1}],'evolution':{'completed':True}}
def fixture(tmp):
 row={'id':'l1/evolving/hermes/s02','level':'l1','agent':'hermes','condition':'evolving','flow_id':'flow','turns':['t1','t2'],'output':str(tmp/'out')}
 turns=[turn('t1',0),turn('t2',.7)]
 put(Path(row['output'])/'flow/summary.json',{'flow_id':'flow','baseline':'hermes','condition':'evolving','turns':turns})
 return row,turns

def checkpoint(row,turns,n):
 cp=Path(row['output'])/'_checkpoints/flow'/f't{n:04d}';cp.mkdir(parents=True)
 put(cp/'checkpoint.json',{'flow_id':'flow','baseline':'hermes','condition':'evolving','next_turn_index':n,'exact_baseline_state':True})
 put(cp/'completed_turns.json',turns[:n]);(cp/'workspace.zip').write_bytes(b'workspace');(cp/'baseline_state.zip').write_bytes(b'state')
 return cp

def test_valid_low_scores_are_kept_without_historical_max(tmp_path):
 row,turns=fixture(tmp_path);selected,source,meta,issues=a.select_evidence(row)
 assert [x['score'] for x in selected]==[0,.7] and not issues
 turns[0]['interactions']=[{'index':1,'score':1,'passed':False},{'index':2,'score':0,'passed':False}]
 assert a.transcript_check(row,turns[0],source,a.TraceReader())['verified']

def test_hold_only_permits_valid_prefix_and_never_quarantined_suffix(tmp_path):
 row,turns=fixture(tmp_path);checkpoint(row,turns,1);checkpoint(row,turns,2)
 put(Path(row['output'])/'_learning_continuity_hold.json',{'status':'unresolved','valid_prefix_turns':1})
 selected,_,_,_=a.select_evidence(row);assert [x['turn_id'] for x in selected]==['t1']

def test_conflicting_paid_histories_are_quarantined_not_best_score_selected(tmp_path):
 row,turns=fixture(tmp_path);different=copy.deepcopy(turns);different[0]['score']=1;different[0]['passed']=True;checkpoint(row,different,2)
 selected,_,_,issues=a.select_evidence(row)
 assert selected==[] and issues[0]['issue']=='conflicting_completed_histories'

@pytest.mark.parametrize('variant',['foreign_condition','nan','infinity','negative','above_one','boolean','passed_number','evaluation_error'])
def test_invalid_summary_never_counts_as_valid_score(tmp_path,variant):
 row,turns=fixture(tmp_path);p=Path(row['output'])/'flow/summary.json';d=json.loads(p.read_text())
 if variant=='foreign_condition':d['condition']='frozen'
 if variant=='nan':d['turns'][0]['score']=float('nan')
 if variant=='infinity':d['turns'][0]['score']=float('inf')
 if variant=='negative':d['turns'][0]['score']=-.1
 if variant=='above_one':d['turns'][0]['score']=1.1
 if variant=='boolean':d['turns'][0]['score']=True
 if variant=='passed_number':d['turns'][0]['passed']=1
 if variant=='evaluation_error':d['turns'][0]['evaluation_status']='evaluation_error'
 put(p,d);assert not a.select_evidence(row)[0]

def test_post_evolution_embedded_score_is_not_compared_to_pre_evolution_live_score(tmp_path):
 row,turns=fixture(tmp_path);t=turns[1]
 assert a.transcript_check(row,t,tmp_path/'source',a.TraceReader())['verified']
 t['interactions'][-1]['score']=1
 assert not a.transcript_check(row,t,tmp_path/'source',a.TraceReader())['verified']

def l2_fixture(tmp):
 row={'level':'l2'};e={'completed':False,'events':[{'type':'evolution.limit_exhausted'}]};trace=tmp/'trace.jsonl'
 record={'turn_id':'t1','interaction_index':1,'score':.25,'passed':True,'evaluation_status':'graded'}
 trace.write_text(json.dumps(record)+'\n'+json.dumps({'record_type':'evolution','turn_id':'t1','evolution':e})+'\n')
 t={'turn_id':'t1','turn_score':.25,'final_score':.25,'passed':False,'interaction_count':1,'evolution':e,'trace_file':str(trace),'recovered_bounded_evolution_failure':True}
 return row,t,trace

def test_failed_evolution_retains_score_but_cannot_become_success(tmp_path):
 row,t,trace=l2_fixture(tmp_path);assert a.transcript_check(row,t,tmp_path/'report.json',a.TraceReader())['verified']
 assert a.learning_tags(t)['derived_bounded_failure'] and a.learning_tags(t)['completed'] is False
 t['passed']=True;assert not a.transcript_check(row,t,tmp_path/'report.json',a.TraceReader())['verified']

def test_duplicate_or_missing_raw_interaction_is_not_verified(tmp_path):
 row,t,trace=l2_fixture(tmp_path);first=trace.read_text().splitlines()[0];trace.write_text(first+'\n'+trace.read_text())
 assert not a.transcript_check(row,t,tmp_path/'report.json',a.TraceReader())['verified']

def test_wrong_evolution_record_is_not_verified(tmp_path):
 row,t,trace=l2_fixture(tmp_path);t['evolution']={'completed':True}
 assert not a.transcript_check(row,t,tmp_path/'report.json',a.TraceReader())['verified']


@pytest.mark.parametrize('variant',['valid','different_reply','wrong_archive','foreign_run'])
def test_resumed_raw_suffix_requires_exact_adjudication_saved_history(tmp_path,variant):
 import hashlib
 row,t,_=l2_fixture(tmp_path)
 out=tmp_path/'job';trace=out/'flow/run/trace.jsonl';trace.parent.mkdir(parents=True)
 row.update(id='l2/frozen/hermes/s02',agent='hermes',condition='frozen',flow_id='flow',turns=['t1'],output=str(out))
 e=t['evolution'];raw={'turn_id':'t1','interaction_index':2,'request':'followup','response':'paid last','tool_calls':[],'score':.25,'passed':True,'evaluation_status':'passed'}
 trace.write_text(json.dumps(raw)+'\n'+json.dumps({'record_type':'evolution','turn_id':'t1','evolution':e})+'\n');t.update(trace_file=str(trace),interaction_count=2)
 cp=out/'_checkpoints/key/run/p0000-02';cp.mkdir(parents=True);(cp/'baseline_state.zip').write_bytes(b'state');(cp/'workspace.zip').write_bytes(b'workspace');put(cp/'completed_turns.json',[])
 meta={'phase':'adjudicate','run_id':'foreign' if variant=='foreign_run' else 'run','stream_id':'flow','baseline':'hermes','condition':'frozen','next_turn_index':0,'turn_id':'t1','interaction_index':2,'learner_state_digest':'wrong' if variant=='wrong_archive' else hashlib.sha256(b'state').hexdigest()};put(cp/'checkpoint.json',meta)
 first={'turn_id':'t1','interaction_index':1,'request':'first','response':'paid first','tool_calls':[],'score':0,'passed':False,'evaluation_status':'failed'}
 put(cp/'evidence.json',{'turn_id':'t1','turn_index':0,'interaction_index':2,'request':'followup','reply':{'text':'foreign reply' if variant=='different_reply' else 'paid last','tool_calls':[]},'interactions':[first]})
 check=a.transcript_check(row,t,tmp_path/'report.json',a.TraceReader())
 assert check['verified']==(variant=='valid')
 if variant=='valid':assert check['saved_history_provenance']['checkpoint']==str(cp)


def test_incomplete_live_checkpoint_keeps_previous_durable_prefix(tmp_path):
 row,turns=fixture(tmp_path);(Path(row['output'])/'flow/summary.json').unlink()
 checkpoint(row,turns,1);bad=checkpoint(row,turns,2);(bad/'checkpoint.json').write_text('')
 selected,_,_,_=a.select_evidence(row)
 assert [x['turn_id'] for x in selected]==['t1']


def test_unpaid_disabled_barrier_is_disclosed_without_calling_it_learning_failure():
 t=turn('t1',.275);t['recovered_unpaid_disabled_barrier']=True
 tags=a.learning_tags(t)
 assert tags['unpaid_disabled_barrier_restoration'] and not tags['derived_bounded_failure']
 assert tags['completed'] is True and not tags['state_changed']
