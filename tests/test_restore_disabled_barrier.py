from pathlib import Path
import hashlib,json,zipfile
import pytest
from tools import restore_disabled_barrier as v


def put(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))


def archive(p,items):
    p.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(p,'w') as z:
        for key,value in items.items():z.writestr(key,value)


def fixture(tmp):
    output=tmp/'original';run=output/'stream/failed';run.mkdir(parents=True)
    row={'level':'l2','id':'l2/frozen/adaptive-auto-harness/s01','agent':'adaptive-auto-harness','flow_id':'stream','condition':'frozen','turns':['t1','t2','t3'],'output':str(output),'status':'paused_error'}
    prefix=[{'turn_id':'t1','condition':'frozen','turn_score':0,'passed':False,'evaluation_status':'failed','final_category':'fail'}]
    cp=output/'_checkpoints/key/failed/p0001-01';cp.mkdir(parents=True)
    archive(cp/'baseline_state.zip',{'memory.md':'original unchanged','.trievo_semantic_state.json':'{}'})
    archive(cp/'workspace.zip',{'artifact.txt':'paid original artifact'});archive(run/'error_workspace.zip',{'artifact.txt':'paid original artifact'})
    put(cp/'checkpoint.json',{'phase':'adjudicate','run_id':'failed','stream_id':'stream','baseline':'adaptive-auto-harness','condition':'frozen','next_turn_index':1,'turn_id':'t2','interaction_index':1,'learner_state_digest':v.sha(cp/'baseline_state.zip')});put(cp/'completed_turns.json',prefix)
    final={'turn_id':'t2','interaction_index':1,'request':'original','response':'paid original reply','tool_calls':[],'score':.275,'passed':False,'evaluation_status':'failed','verifier':{'category':'fail'}}
    put(cp/'evidence.json',{'turn_id':'t2','turn_index':1,'interaction_index':1,'request':'original','reply':{'text':'paid original reply','tool_calls':[]},'interactions':[]});(run/'trace.jsonl').write_text(json.dumps(final)+'\n')
    snapshot=v.snapshot_from_checkpoint(cp/'baseline_state.zip');failure=run/'failed_evolution/export';put(failure/'failure.json',{'turn_id':'t2','recoverable_checkpoint':False,'state_digest':snapshot['digest']});put(failure/'baseline_state_snapshot.json',snapshot);archive(failure/'baseline_state.zip',{'memory.md':'original unchanged'})
    report={'run_id':'failed','stream_id':'stream','baseline':'adaptive-auto-harness','condition':'frozen','turns':prefix,'error':'BaselineProtocolError: baseline adapter response id mismatch: expected 7, got None','finished_at':'original-finish','token_budget':{'limit':10000000,'used':300,'calls':4},'run_configuration':{'effective_work_limits':{'evolution_timeout_seconds':120},'execution_requirements':{'max_interactions':1}}};put(run/'report.json',report)
    return row,run,cp,report,final


def native(row,proof):
    return {'network':'none','model_calls':0,'job':row['id'],'proof_key':proof['key'],'evolve_result':{'completed':True,'events':[{'type':'evolution.skipped','reason':'condition:frozen'}],'usage':{}},'state_unchanged':True,'workspace_unchanged':True}


def test_original_low_grade_preserved_unpaid_skip_not_successful_learning(tmp_path):
    row,run,cp,report,final=fixture(tmp_path);proof=v.inspect_disabled(row,run/'report.json');original={str(p):p.read_bytes() for p in Path(row['output']).rglob('*') if p.is_file()}
    result=v.materialize(row,proof,native(row,proof),tmp_path/'derived');d=json.loads(Path(result['report']).read_text());t=d['turns'][-1]
    assert t['turn_score']==.275 and t['passed'] is False and t['evolution']['completed'] is True
    assert t['evolution']['events'][0]['type']=='evolution.skipped' and t['evolution']['state_before']==t['evolution']['state_after']
    assert d['token_budget']==report['token_budget'] and result['additional_model_calls']==0
    assert original=={str(p):p.read_bytes() for p in Path(row['output']).rglob('*') if p.is_file()}


@pytest.mark.parametrize('bad',['evolving','missing_export','changed_workspace','changed_native_state','nonterminal','reply_changed','already_completed_barrier','hold'])
def test_unsafe_disabled_barriers_are_not_completed(tmp_path,bad):
    row,run,cp,report,final=fixture(tmp_path)
    if bad=='evolving':row['condition']='evolving'
    if bad=='missing_export':(run/'failed_evolution/export/failure.json').unlink()
    if bad=='changed_workspace':archive(run/'error_workspace.zip',{'artifact.txt':'changed'})
    if bad=='changed_native_state':archive(run/'failed_evolution/export/baseline_state.zip',{'memory.md':'changed'})
    if bad=='nonterminal':report['run_configuration']['execution_requirements']['max_interactions']=3;put(run/'report.json',report)
    if bad=='reply_changed':final['response']='another reply';(run/'trace.jsonl').write_text(json.dumps(final)+'\n')
    if bad=='already_completed_barrier':
        with (run/'trace.jsonl').open('a') as f:f.write(json.dumps({'turn_id':'t2','record_type':'evolution'})+'\n')
    if bad=='hold':put(Path(row['output'])/'_learning_continuity_hold.json',{'status':'unresolved','valid_prefix_turns':1})
    with pytest.raises((ValueError,OSError)):v.inspect_disabled(row,run/'report.json')


@pytest.mark.parametrize('bad',['network','model_call','wrong_job','wrong_key','state_changed','not_skipped','source_changed'])
def test_unbound_native_recovery_receipt_refused(tmp_path,bad):
    row,run,cp,report,final=fixture(tmp_path);proof=v.inspect_disabled(row,run/'report.json');receipt=native(row,proof)
    if bad=='network':receipt['network']='host'
    if bad=='model_call':receipt['model_calls']=1
    if bad=='wrong_job':receipt['job']='foreign'
    if bad=='wrong_key':receipt['proof_key']='foreign'
    if bad=='state_changed':receipt['state_unchanged']=False
    if bad=='not_skipped':receipt['evolve_result']['events']=[{'type':'evolution.completed'}]
    if bad=='source_changed':(run/'trace.jsonl').write_text('changed')
    with pytest.raises(ValueError):v.materialize(row,proof,receipt,tmp_path/'derived')
    assert not (tmp_path/'derived').exists()

def test_reset_failed_export_must_be_in_the_exact_turn_segment(tmp_path):
    import shutil
    row,run,cp,report,final=fixture(tmp_path)
    row.update(id='l2/reset/adaptive-auto-harness/s01',condition='reset')
    report['condition']='reset';report['turns'][0]['condition']='reset';put(run/'report.json',report)
    meta=json.loads((cp/'checkpoint.json').read_text());meta['condition']='reset';put(cp/'checkpoint.json',meta);put(cp/'completed_turns.json',report['turns'])
    exact=run/'runtime_segments/t0002/failed_evolution';exact.parent.mkdir(parents=True)
    shutil.move(str(run/'failed_evolution'),str(exact))
    assert v.inspect_disabled(row,run/'report.json')['target']=='t2'
    wrong=run/'runtime_segments/t0003';wrong.mkdir()
    shutil.move(str(exact),str(wrong/'failed_evolution'))
    with pytest.raises(ValueError,match='missing exact'):
        v.inspect_disabled(row,run/'report.json')


def test_separate_workspace_audit_keeps_exact_bytes_and_resource_bound(tmp_path):
    a=tmp_path/'a.zip';b=tmp_path/'b.zip'
    archive(a,{'artifact.txt':'same contents'});archive(b,{'artifact.txt':'same contents'})
    with pytest.raises(ValueError,match='limit'):
        v.compare_workspace_archives(a,b,max_bytes=4)
    assert v.compare_workspace_archives(a,b,max_bytes=100)['equal']
    archive(b,{'artifact.txt':'different content'})
    assert not v.compare_workspace_archives(a,b,max_bytes=100)['equal']
    with pytest.raises(ValueError):v.compare_workspace_archives(a,b,max_bytes=8*1024**3)


@pytest.mark.parametrize('name',['../escape','/absolute','back\\slash'])
def test_separate_workspace_audit_never_accepts_unsafe_paths(tmp_path,name):
    a=tmp_path/'a.zip'
    # Patch both ZIP headers to preserve the literal hostile name on Windows.
    marker = 'x' * len(name)
    archive(a, {marker: 'unsafe'})
    a.write_bytes(a.read_bytes().replace(marker.encode('ascii'), name.encode('ascii')))
    with zipfile.ZipFile(a) as bundle:
        assert [entry.orig_filename for entry in bundle.infolist()] == [name]
    with pytest.raises(ValueError,match='unsafe'):
        v.compare_workspace_archives(a,a,max_bytes=100)


def test_completed_target_in_any_preserved_run_is_never_recreated(tmp_path,monkeypatch):
    row,run,cp,report,final=fixture(tmp_path)
    monkeypatch.setattr(v,'completed_target_evidence',lambda *args:{'existing':'valid_turn'})
    with pytest.raises(ValueError,match='already completed'):
        v.inspect_disabled(row,run/'report.json')


def test_newer_unreturned_interaction_blocks_old_unpaid_barrier_selection(tmp_path):
    row,run,cp,report,final=fixture(tmp_path)
    newer=Path(row['output'])/'_checkpoints/key/another/i0001-01'
    put(newer/'checkpoint.json',{'phase':'interact_started','run_id':'another','stream_id':'stream','baseline':'adaptive-auto-harness','condition':'frozen','next_turn_index':1,'turn_id':'t2','interaction_index':1})
    with pytest.raises(ValueError):v.inspect_disabled(row,run/'report.json')
