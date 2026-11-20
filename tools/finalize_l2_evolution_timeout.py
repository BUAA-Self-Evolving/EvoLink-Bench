"""Finalize a proven exhausted learning barrier without repeating paid work.

The Agent/Judge result is retained. Evolution remains FAILED, pre-learning state
is restored, and unknown failed usage stays unknown. This is never a success
conversion or an extra learning attempt.
"""
from pathlib import Path,PurePosixPath
import copy,hashlib,json,math,shutil,zipfile
from tools.run_new_package_matrix import _checkpoint_preserves_prefix,_report_matches_row,learning_continuity_prefix

ERROR='BaselineProtocolError: baseline adapter timed out during evolve'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def archive_inventory(path):
    result={};total=0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name=item.filename;part=PurePosixPath(name)
            if item.is_dir():continue
            if name in result or part.is_absolute() or '..' in part.parts:raise ValueError('unsafe/duplicate archive entry')
            total+=item.file_size
            if total>512*1024**2:raise ValueError('large archive requires separate audit')
            hasher=hashlib.sha256()
            with archive.open(item) as f:
                for data in iter(lambda:f.read(1024*1024),b''):hasher.update(data)
            result[name]={'path':name,'size':item.file_size,'sha256':hasher.hexdigest()}
    return result

def snapshot_from_checkpoint(path):
    inventory=archive_inventory(path);semantic={}
    if '.trievo_semantic_state.json' in inventory:
        with zipfile.ZipFile(path) as archive:semantic=json.loads(archive.read('.trievo_semantic_state.json'))
        if not isinstance(semantic,dict):raise ValueError('invalid semantic state')
        inventory.pop('.trievo_semantic_state.json')
    metadata=[inventory[k] for k in sorted(inventory)];hasher=hashlib.sha256()
    for item in metadata:hasher.update(item['path'].encode());hasher.update(item['sha256'].encode('ascii'))
    digest=hasher.hexdigest()
    return {'state':{'digest':digest,'files':[x['path'] for x in metadata],**semantic},'digest':digest,'files':metadata}

def inspect_timeout(row,report_path,*,failed_workspace_review=None):
    if row.get('level')!='l2' or row.get('condition')!='evolving' or learning_continuity_prefix(row) is not None:
        raise ValueError('requires an unheld evolving L2 frontier')
    if row.get('status') not in ('paused_error','needs_attention','blocked_recovery'):raise ValueError('job is owned or complete')
    p=Path(report_path).resolve();output=Path(row['output']).resolve()
    if output not in p.parents:raise ValueError('foreign report')
    report=json.loads(p.read_text());n=len(report.get('turns',[]))
    if report.get('error')!=ERROR or not report.get('finished_at') or n>=len(row['turns']):raise ValueError('not a finished exact learning timeout')
    config=report.get('run_configuration',{});limits=config.get('effective_work_limits',{})
    if limits.get('evolution_timeout_seconds')!=120 or config.get('budget_profile','formal')!='formal':raise ValueError('not the original formal 120s budget')
    prefix={**row,'turns':row['turns'][:n]};clean={**report,'error':None,'cleanup_error':None}
    if not _report_matches_row(prefix,clean):raise ValueError('invalid original completed prefix')
    target=row['turns'][n];pending=[]
    for meta_path in (output/'_checkpoints').rglob('checkpoint.json'):
        meta=json.loads(meta_path.read_text())
        if meta.get('run_id')==report['run_id'] and meta.get('turn_id')==target and meta.get('phase')=='adjudicate' and not meta.get('invalidated'):
            pending.append((meta['interaction_index'],meta_path.parent,meta))
    if not pending:raise ValueError('missing exact final saved-reply checkpoint')
    k,cp,meta=max(pending);_checkpoint_preserves_prefix(row,cp,n)
    if meta.get('learner_state_digest')!=sha(cp/'baseline_state.zip'):raise ValueError('learner archive digest mismatch')
    trace=p.parent/'trace.jsonl';records=[json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    if any(x.get('turn_id')==target and x.get('record_type')=='evolution' for x in records):raise ValueError('already has paid evolution completion evidence')
    final=[x for x in records if x.get('turn_id')==target and x.get('interaction_index')==k and 'record_type' not in x]
    if len(final)!=1:raise ValueError('missing/duplicate terminal adjudication')
    final=final[0];evidence=json.loads((cp/'evidence.json').read_text());reply=evidence.get('reply',{})
    if final.get('response')!=reply.get('text') or final.get('request')!=evidence.get('request') or final.get('tool_calls',[])!=reply.get('tool_calls',[]):
        raise ValueError('terminal reply does not match durable paid evidence')
    interactions=evidence.get('interactions',[])+[final]
    if [x.get('interaction_index') for x in interactions]!=list(range(1,k+1)):raise ValueError('incomplete paid Interaction history')
    if any(x.get('turn_id')!=target or x.get('evaluation_status')=='evaluation_error' or x.get('terminal_evaluation_error') for x in interactions):raise ValueError('unresolved evaluator failure')
    score=final.get('score')
    if type(score) not in (int,float) or not math.isfinite(score) or type(final.get('passed')) is not bool:raise ValueError('invalid terminal score')
    maximum=config.get('execution_requirements',{}).get('max_interactions')
    if not (final['passed'] or k==maximum or final.get('verifier',{}).get('category')=='execution_limit'):
        raise ValueError('terminality not proven; cannot skip a paid Interaction')
    failed=[]
    for f in (p.parent/'failed_evolution').glob('*/failure.json'):
        d=json.loads(f.read_text())
        if d.get('turn_id')==target and d.get('recoverable_checkpoint') is False:failed.append(f)
    if len(failed)!=1:raise ValueError('missing exact native failed-evolution export')
    workspace=p.parent/'error_workspace.zip'
    task_inventory=archive_inventory(workspace)
    saved_inventory=archive_inventory(cp/'workspace.zip')
    review_bindings={};workspace_recovery=None
    if failed_workspace_review is not None:
        # Explicit, independently reviewed skip of an already exhausted Prime
        # attempt. Preserve the ACTUAL post-timeout task bytes; roll back only
        # the declared learner state, as ProcessBaselineRuntime does on bounded
        # recoverable evolution failure. Never call this unchanged-workspace.
        review_path=Path(failed_workspace_review);review=json.loads(review_path.read_text())
        auth_path=Path(review['authorization']);auth=json.loads(auth_path.read_text())
        if review.get('policy')!='prime_exhausted_turn_preserve_failed_task_workspace' or row.get('agent')!='prime-agent':
            raise ValueError('not the narrowly reviewed Prime failure policy')
        if auth.get('user_statement')!='合法预算耗尽就当作失败，跳过当前turn就行' or row['id'] not in auth.get('jobs',[]):
            raise ValueError('missing exact budget-skip authorization')
        if review.get('authorization_sha256')!=sha(auth_path):raise ValueError('authorization changed')
        expected={'job':row['id'],'report_sha256':sha(p),'checkpoint_sha256':sha(cp/'checkpoint.json'),
                  'task_workspace_sha256':sha(workspace),'learner_state_sha256':sha(cp/'baseline_state.zip'),
                  'failure_sha256':sha(failed[0])}
        if any(review.get(k)!=v for k,v in expected.items()):raise ValueError('workspace review does not bind exact original evidence')
        verifier=final.get('verifier',{});details=verifier.get('details',{})
        if verifier.get('category')!='execution_limit' or details.get('type')!='work_limit' or details.get('reason') not in ('max_tool_calls','max_model_calls') or score!=0 or final['passed'] is not False:
            raise ValueError('original current-Turn resource failure is not proven')
        budget=report.get('token_budget',{})
        if budget!=meta.get('token_budget') or not all(type(budget.get(k)) is int and budget[k]>=0 for k in ('limit','used','calls')) or not 0<budget['limit'] or budget['used']>budget['limit']:
            raise ValueError('original cumulative budget receipt mismatch')
        export=failed[0].parent
        for extra in ('baseline_state.zip','baseline_state_snapshot.json'):
            if not (export/extra).is_file():raise ValueError('missing original failed-learner export')
            review_bindings[str(export/extra)]=sha(export/extra)
        archive_inventory(export/'baseline_state.zip')
        workspace_recovery={'policy':review['policy'],'task_workspace':str(workspace),'task_workspace_sha256':sha(workspace),
                            'original_post_failure_task_bytes_preserved':True,'workspace_unchanged_claimed':False,
                            'failed_learning_state_adopted':False,'review':str(review_path),
                            'task_changed_paths':[k for k in sorted(set(task_inventory)|set(saved_inventory)) if task_inventory.get(k)!=saved_inventory.get(k)]}
        review_bindings.update({str(review_path):sha(review_path),str(auth_path):sha(auth_path)})
    elif task_inventory!=saved_inventory:
        raise ValueError('task workspace changed after final reply; separate reconstruction required')
    # Later native mutations are deliberately not used as a successful update.
    # Restore exactly the saved pre-learning archive, matching the runtime's
    # existing recoverable_failure rollback semantics.
    snapshot=snapshot_from_checkpoint(cp/'baseline_state.zip')
    files=[p,trace,cp/'checkpoint.json',cp/'evidence.json',cp/'completed_turns.json',cp/'baseline_state.zip',cp/'workspace.zip',workspace,failed[0]]
    bindings={str(f):sha(f) for f in files};bindings.update(review_bindings)
    key=hashlib.sha256(json.dumps({'job':row['id'],'run':report['run_id'],'turn':target,'bindings':bindings},sort_keys=True).encode()).hexdigest()
    proof={'job':row['id'],'key':key,'failed_run_id':report['run_id'],'turn_id':target,'turn_index':n,'interaction_index':k,'checkpoint':str(cp),'report':str(p),'bindings':bindings,'snapshot':snapshot,'score':score,'terminal_category':final.get('verifier',{}).get('category'),'formal_evolution_timeout_seconds':120,'additional_model_calls':0,'failed_evolution_usage_status':'unknown'}
    if workspace_recovery is not None:proof['task_workspace_recovery']=workspace_recovery
    return proof,report,final,interactions

def materialize(row,inspection,branch_output):
    proof,original,final,interactions=inspection
    for path,digest in proof['bindings'].items():
        if sha(path)!=digest:raise ValueError('bound evidence changed')
    output=Path(branch_output);runid='evofail-'+proof['key'][:24];run=output/row['flow_id']/runid;run.mkdir(parents=True)
    n=proof['turn_index'];target=proof['turn_id'];cp=Path(proof['checkpoint']);checkpoint=output/'_checkpoints'/hashlib.sha256(row['flow_id'].encode()).hexdigest()[:10]/runid[-8:]/f't{n+1:04d}';checkpoint.mkdir(parents=True)
    evolution={'completed':False,'events':[{'type':'evolution.limit_exhausted','reason':'original_native_evolve_120s_timeout','recovered_without_additional_model_calls':True}],
               'usage':{},'usage_status':'unknown_failed_evolution','state_before':proof['snapshot'],'state_after':proof['snapshot'],'changed_files':[]}
    report=copy.deepcopy(original);report.pop('error',None);report.pop('cleanup_error',None)
    report.update(run_id=runid,stopped_after_turn=target,completed=n+1==len(row['turns']),evaluation_complete=True,success=False,
                  infrastructure_recovery={'type':'bounded_evolution_failure_finalization','source_report':proof['report'],'source_error':ERROR,'failed_evolution_is_not_success':True,'additional_model_calls':0,'proof_key':proof['key'],'failed_usage_status':'unknown'})
    trace=run/'trace.jsonl';trace.write_bytes((Path(proof['report']).parent/'trace.jsonl').read_bytes())
    with trace.open('a') as f:f.write('\n'+json.dumps({'record_type':'evolution','turn_id':target,'evolution':evolution})+'\n')
    report['turns'].append({'condition':row['condition'],'stream_id':row['flow_id'],'turn_id':target,'turn_index':n+1,'sequence_role':row.get('turn_roles',{}).get(target),
       'turn_score':proof['score'],'evaluation_status':final['evaluation_status'],'passed':False,'final_score':proof['score'],'final_category':'evolution_limit','interaction_count':len(interactions),
       'trace_file':str(trace),'evolution':evolution,'effective_work_limits':original['run_configuration']['effective_work_limits'],'checkpoint':str(checkpoint),'recovered_bounded_evolution_failure':True})
    for name in ['workspace.zip','baseline_state.zip']:
        source=Path(proof['task_workspace_recovery']['task_workspace']) if name=='workspace.zip' and proof.get('task_workspace_recovery') else cp/name
        shutil.copy2(source,checkpoint/name)
    if proof.get('task_workspace_recovery'):
        report['infrastructure_recovery']['task_workspace_recovery']=proof['task_workspace_recovery']
    meta=json.loads((cp/'checkpoint.json').read_text());meta.pop('phase',None);meta.pop('interaction_index',None)
    meta.update(run_id=runid,failed_run_id=proof['failed_run_id'],completed_turn_index=n,next_turn_index=n+1,token_budget=original.get('token_budget',{}),recovery_type='bounded_evolution_failure_without_model_retry')
    (checkpoint/'checkpoint.json').write_text(json.dumps(meta,indent=2));(checkpoint/'completed_turns.json').write_text(json.dumps(report['turns'],indent=2))
    (run/'report.json').write_text(json.dumps(report,indent=2));(run/'recovery-proof.json').write_text(json.dumps(proof,indent=2))
    partial={**row,'output':str(output),'turns':row['turns'][:n+1]}
    if not _report_matches_row(partial,report):raise ValueError('recovered failed outcome does not validate')
    _checkpoint_preserves_prefix(partial,checkpoint,n+1)
    return {'report':str(run/'report.json'),'checkpoint':str(checkpoint),'output':str(output),'proof_key':proof['key'],'turn_id':target,'completed_prefix_turns':n+1,'additional_model_calls':0,'evolution_completed':False}
