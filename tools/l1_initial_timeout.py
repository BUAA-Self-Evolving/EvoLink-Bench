"""Independent initial-Turn recovery; never invent an original checkpoint/counter.

The original paid answer and failed learning are retained. The task is the
proven post-answer snapshot; the learner export must equal its pre-answer
declared state. A separate conservative fuse uses the public CLI default,
explicitly not an asserted original CLI ceiling or failure counter receipt.
"""
from pathlib import Path
import ast, copy, hashlib, json, shutil, zipfile
from tools.l1_rejected_learning import sha, load
from tools.finalize_l2_evolution_timeout import snapshot_from_checkpoint
from tools.run_new_package_matrix import latest_checkpoint, _checkpoint_preserves_prefix

SCHEMA='trievo.independent-initial-l1-timeout.v1'
ERROR='evolink_bench.baselines.process.BaselineProtocolError: baseline adapter timed out during evolve'

def public_default_fuse(source):
    tree=ast.parse(Path(source).read_text(encoding='utf-8-sig'))
    values=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument' and any(isinstance(a,ast.Constant) and a.value=='--max-total-tokens' for a in node.args):
            values.extend(k.value.value for k in node.keywords if k.arg=='default' and isinstance(k.value,ast.Constant))
    if values!=[3_000_000]: raise ValueError('separately reviewed conservative default fuse required')
    return values[0]

def inspect(row, restoration_review, restored_workspace, authorization, cli_source):
    auth=load(authorization)
    if (row.get('level'),row.get('condition'),row.get('agent'))!=('l1','evolving','adaptive-auto-harness'):
        raise ValueError('requires initial Adaptive evolving L1')
    if row.get('status') not in ('paused_error','needs_attention','blocked_recovery') or latest_checkpoint(row) is not None:
        raise ValueError('requires unowned original initial Turn with no committed CP')
    if (auth.get('schema')!=SCHEMA or auth.get('job')!=row['id']
        or auth.get('policy')!='independent_initial_timeout_original_paid_answer_preserved'
        or auth.get('failed_learning_usage')!='unknown' or auth.get('additional_learning_attempts')!=0
        or auth.get('original_native_budget_receipt_claimed') is not False
        or auth.get('post_failure_exact_continuation_claimed') is not False
        or auth.get('aggregate_policy')!='separate_conservative_public_cli_default_fuse'):
        raise ValueError('explicit independent initial recovery and unknown-cost authority required')
    fuse=public_default_fuse(cli_source)
    if auth.get('independent_fuse')!=fuse: raise ValueError('independent fuse changed')
    flow=Path(row['output'])/row['flow_id'];trace=flow/'live_trace.jsonl'
    pending=[json.loads(x) for x in trace.read_text(encoding='utf-8').splitlines() if x.strip()]
    if not pending or any(x.get('turn_id')!=row['turns'][0] for x in pending) or [x.get('index') for x in pending]!=list(range(1,len(pending)+1)):
        raise ValueError('later/duplicate paid history requires separate adjudication')
    final=pending[-1]
    if final.get('score')!=1.0 or final.get('passed') is not True or not final.get('response') or final.get('action_error'):
        raise ValueError('requires original successful terminal answer')
    if any(x.get('verifier_details',{}).get('type') in ('model_error','verifier_model_error','exec_verifier_timeout') for x in pending):
        raise ValueError('unresolved evaluator failure')
    log=Path(row['log']);error=log.read_text(errors='replace').splitlines()[-1]
    if error!=ERROR: raise ValueError('not the original initial evolution timeout')
    failures=list(flow.glob('failed_evolution/*/failure.json'))
    if len(failures)!=1: raise ValueError('ambiguous failed learner export')
    failed=failures[0];failure=load(failed);archive=failed.parent/'baseline_state.zip';snapfile=failed.parent/'baseline_state_snapshot.json'
    snap=snapshot_from_checkpoint(archive)
    if (failure.get('turn_id')!=row['turns'][0] or failure.get('recoverable_checkpoint') is not False
        or failure.get('state_digest')!=snap['digest'] or load(snapfile)!=snap
        or any(x.get('state_before',{}).get('digest')!=snap['digest'] or x.get('state_before',{}).get('files')!=snap['state']['files'] for x in pending)):
        raise ValueError('initial declared learner changed or identity unproven')
    # No synthetic semantic checkpoint metadata is inserted into the archive.
    with zipfile.ZipFile(archive) as z:
        if '.trievo_semantic_state.json' in z.namelist(): raise ValueError('initial semantic state needs separate review')
    review=[x for x in load(restoration_review)['results'] if x['job']==row['id']]
    if len(review)!=1 or not review[0].get('exact_original_post_answer_snapshot_restored'):
        raise ValueError('full original post-answer restoration required')
    work=Path(restored_workspace)
    if any(p.is_symlink() for p in work.rglob('*')): raise ValueError('symlink task state')
    actual={p.relative_to(work).as_posix():{'size':p.stat().st_size,'sha256':sha(p)} for p in work.rglob('*') if p.is_file()}
    expected={x['path'].removeprefix('/workspace/'):{'size':x['size'],'sha256':x['sha256']} for x in final['sandbox']['files']}
    if actual!=expected or len(actual)!=review[0]['file_count']: raise ValueError('original post-answer task bytes differ')
    budget={'limit':fuse,'used':0,'calls':0}
    for x in pending:
        u=x['usage']
        if type(u.get('total_tokens')) is not int or u['total_tokens']<0 or type(u.get('api_calls')) is not int or u['api_calls']<=0:
            raise ValueError('original paid usage lower bound unavailable')
        budget['used']+=u['total_tokens'];budget['calls']+=u['api_calls']
    if budget['used']>=fuse: raise ValueError('independent conservative fuse exhausted')
    files=[Path(authorization),Path(restoration_review),Path(cli_source),trace,log,failed,archive,snapfile]
    proof={'schema':SCHEMA,'job':row['id'],'target':row['turns'][0],'authorization':str(authorization),
        'restoration_review':str(restoration_review),'restored_workspace':str(work),'cli_source':str(cli_source),
        'bindings':{str(p.resolve()):sha(p) for p in files},'original_failed_archive':str(archive),'snapshot':snap,
        'task_inventory':expected,'derived_known_budget_lower_bound':budget,'original_aggregate_ceiling':'unknown_missing_native_cli_receipt',
        'independent_aggregate_fuse_is_original_ceiling':False,'native_remaining_counter_receipt_claimed':False,
        'prior_original_checkpoint_exists':False,'exact_post_failure_workspace_claimed':False,
        'unknown_failed_learning_usage_preserved':True,'agent_judge_learning_replays':0,'original_error':error}
    proof['key']=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest()
    return proof,pending

def materialize(row, inspection, output):
    proof,pending=inspection
    fresh=inspect(row,proof['restoration_review'],proof['restored_workspace'],proof['authorization'],proof['cli_source'])
    if fresh!=inspection: raise ValueError('inspection changed or forged')
    output=Path(output)
    if output.exists(): raise ValueError('independent output already exists')
    cp=output/'_checkpoints'/hashlib.sha256(row['flow_id'].encode()).hexdigest()[:10]/'t0001';cp.mkdir(parents=True)
    evo={'completed':False,'events':[{'type':'evolution.failed','message':proof['original_error'],'recovered_without_retry':True}],
        'usage':{},'usage_status':'unknown_original_failed_learning','state_before':proof['snapshot'],'state_after':proof['snapshot'],'changed_files':[],
        'independent_recovery':{k:proof[k] for k in ('schema','key','unknown_failed_learning_usage_preserved','native_remaining_counter_receipt_claimed','exact_post_failure_workspace_claimed','independent_aggregate_fuse_is_original_ceiling')}}
    record={'turn_id':proof['target'],'score':pending[-1]['score'],'passed':pending[-1]['passed'],
        'interactions':[{k:v for k,v in x.items() if k!='turn_id'} for x in pending],'evolution':evo}
    meta={'flow_id':row['flow_id'],'baseline':row['agent'],'condition':'evolving','completed_turn_index':0,'next_turn_index':1,
        'turn_id':proof['target'],'token_budget':proof['derived_known_budget_lower_bound'],'exact_baseline_state':True,
        'independent_recovery':{'schema':SCHEMA,'proof':str(output/'recovery-proof.json'),'key':proof['key'],'budget_is_known_lower_bound':True,
        'historical_unknown_usage':True,'original_native_checkpoint_claimed':False,'original_aggregate_ceiling_claimed':False,'post_failure_exact_continuation_claimed':False}}
    shutil.copyfile(proof['original_failed_archive'],cp/'baseline_state.zip')
    with zipfile.ZipFile(cp/'workspace.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(proof['task_inventory']):z.write(Path(proof['restored_workspace'])/name,name)
    for name,data in [('checkpoint.json',meta),('completed_turns.json',[record])]: (cp/name).write_text(json.dumps(data,indent=2),encoding='utf-8')
    (output/'recovery-proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    _checkpoint_preserves_prefix({**row,'output':str(output)},cp,1)
    return {'checkpoint':str(cp),'output':str(output),'proof_key':proof['key'],'saved_score':record['score'],'new_model_calls':0}

def validate_adoption(row):
    p=Path(row['l1_initial_timeout_authorization'])
    if sha(p)!=row['l1_initial_timeout_authorization_sha256']: raise ValueError('initial timeout authority changed')
    a=load(p)
    if a.get('schema')!=SCHEMA or a.get('job')!=row['id'] or a.get('output')!=row['output']: raise ValueError('initial timeout identity changed')
    proof=load(Path(row['output'])/'recovery-proof.json')
    if inspect(a['original_row'],proof['restoration_review'],proof['restored_workspace'],proof['authorization'],proof['cli_source'])[0]!=proof or a.get('proof_key')!=proof['key']:
        raise ValueError('initial recovery original evidence changed')
    for x in a['initial_checkpoint_bindings'].values():
        if sha(x['path'])!=x['sha256']: raise ValueError('initial independent checkpoint changed')
    return a
