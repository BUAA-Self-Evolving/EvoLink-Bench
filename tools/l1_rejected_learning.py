"""Independent finalization of a saved L1 answer after rejected Adaptive learning.

Never invokes Agent, Judge or evolution. Task bytes are the proven post-answer
snapshot, not a claimed post-failure capture. Learned files roll back to the
original preceding CP; old failed-learning usage remains explicitly unknown.
"""
from pathlib import Path
import copy, hashlib, json, re, shutil, zipfile
from tools.finalize_l2_evolution_timeout import archive_inventory, snapshot_from_checkpoint
from tools.run_new_package_matrix import latest_checkpoint, _checkpoint_preserves_prefix

SCHEMA='trievo.independent-l1-rejected-learning.v1'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def inspect(row, restoration_review, restored_workspace, authorization):
    auth=load(authorization)
    if (row.get('level'),row.get('condition'),row.get('agent'))!=('l1','evolving','adaptive-auto-harness'):
        raise ValueError('requires Adaptive evolving L1')
    if row.get('status') not in ('paused_error','needs_attention','blocked_recovery'):
        raise ValueError('job is owned or completed')
    if auth.get('schema')!=SCHEMA or auth.get('job')!=row['id'] or auth.get('policy')!='original_answer_preserved_failed_learning_not_retried':
        raise ValueError('missing independent failure-finalization authority')
    if (auth.get('workspace_policy')!='exact_post_answer_snapshot_independent_recovery'
        or auth.get('post_failure_workspace_identity_claimed') is not False
        or auth.get('failed_learning_usage')!='unknown'
        or auth.get('additional_learning_attempts')!=0):
        raise ValueError('independent workspace/unknown-cost policy required')
    output=Path(row['output']);flow=output/row['flow_id'];cp=latest_checkpoint(row)
    if cp is None: raise ValueError('original preceding committed CP required')
    meta=load(cp/'checkpoint.json');prefix=load(cp/'completed_turns.json');n=len(prefix)
    if meta.get('next_turn_index')!=n or not 0<n<len(row['turns']) or meta.get('exact_baseline_state') is not True:
        raise ValueError('invalid original prefix frontier')
    _checkpoint_preserves_prefix(row,cp,n)
    target=row['turns'][n];trace=flow/'live_trace.jsonl';records=[json.loads(x) for x in trace.read_text().splitlines() if x.strip()]
    if any(x.get('turn_id') not in row['turns'][:n+1] for x in records): raise ValueError('later paid records exist')
    pending=[x for x in records if x.get('turn_id')==target]
    if not pending or [x.get('index') for x in pending]!=list(range(1,len(pending)+1)):
        raise ValueError('incomplete/duplicate original saved interactions')
    final=pending[-1]
    if final.get('score')!=1.0 or final.get('passed') is not True or not final.get('response') or final.get('action_error'):
        raise ValueError('requires the original successful terminal answer')
    if any(x.get('verifier_details',{}).get('type') in ('model_error','verifier_model_error','exec_verifier_timeout') for x in pending):
        raise ValueError('unresolved evaluator error')
    log=Path(row['log']);error=log.read_text(errors='replace').splitlines()[-1]
    if not re.fullmatch(r'evolink_bench.baselines.process.BaselineProtocolError: baseline adapter evolve failed: Extra data: line \d+ column \d+ \(char \d+\)',error):
        raise ValueError('not the exact original rejected proposal failure')
    failed=list(flow.glob('failed_evolution/*/failure.json'))
    if len(failed)!=1 or load(failed[0]).get('turn_id')!=target or load(failed[0]).get('recoverable_checkpoint') is not False:
        raise ValueError('missing exact failed evolution export')
    failedzip=failed[0].parent/'baseline_state.zip';failedsnap=failed[0].parent/'baseline_state_snapshot.json'
    old=archive_inventory(cp/'baseline_state.zip');new=archive_inventory(failedzip)
    old.pop('.trievo_semantic_state.json',None);new.pop('.trievo_semantic_state.json',None)
    if old!=new: raise ValueError('declared learned files changed; separate review required')
    snap=snapshot_from_checkpoint(cp/'baseline_state.zip')
    if load(failedsnap).get('digest')!=snap['digest'] or load(failed[0]).get('state_digest')!=snap['digest']:
        raise ValueError('failed learner identity mismatch')
    reviewed=[x for x in load(restoration_review)['results'] if x['job']==row['id']]
    if len(reviewed)!=1 or not reviewed[0].get('exact_original_post_answer_snapshot_restored'):
        raise ValueError('missing full original task restoration review')
    work=Path(restored_workspace)
    actual={p.relative_to(work).as_posix():{'size':p.stat().st_size,'sha256':sha(p)} for p in work.rglob('*') if p.is_file() and not p.is_symlink()}
    expected={x['path'].removeprefix('/workspace/'):{'size':x['size'],'sha256':x['sha256']} for x in final['sandbox']['files']}
    if actual!=expected or len(actual)!=reviewed[0]['file_count'] or any(p.is_symlink() for p in work.rglob('*')):
        raise ValueError('post-answer task bytes differ')
    budget=copy.deepcopy(meta['token_budget'])
    if not all(type(budget.get(k)) is int and budget[k]>=0 for k in ('used','calls','limit')): raise ValueError('invalid original budget')
    for item in pending:
        usage=item['usage'];total=usage.get('total_tokens');calls=usage.get('api_calls')
        if type(total) is not int or total<0 or type(calls) is not int or calls<=0: raise ValueError('saved reply lacks known usage')
        budget['used']+=total;budget['calls']+=calls
    if budget['used']>=budget['limit']: raise ValueError('aggregate fuse exhausted')
    files=[Path(authorization),Path(restoration_review),trace,log,failed[0],failedzip,failedsnap]+[cp/x for x in ('checkpoint.json','completed_turns.json','baseline_state.zip','workspace.zip')]
    bindings={str(p.resolve()):sha(p) for p in files}
    proof={'schema':SCHEMA,'job':row['id'],'target':target,'prefix_count':n,'original_checkpoint':str(cp),
        'restoration_review':str(restoration_review),'authorization':str(authorization),'restored_workspace':str(work),'task_inventory':expected,'bindings':bindings,'original_prefix_budget':meta['token_budget'],
        'derived_known_budget_lower_bound':budget,'unknown_failed_learning_usage_preserved':True,
        'native_remaining_counter_receipt_claimed':False,'exact_post_failure_workspace_claimed':False,
        'failed_learned_state_adopted':False,'agent_judge_learning_replays':0,'snapshot':snap,'original_error':error}
    proof['key']=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest()
    return proof,prefix,pending

def materialize(row,inspection,output):
    proof,prefix,pending=inspection
    fresh=inspect(row,proof['restoration_review'],proof['restored_workspace'],proof['authorization'])
    if fresh!=inspection: raise ValueError('inspection changed or forged')
    for path,digest in proof['bindings'].items():
        if sha(path)!=digest: raise ValueError('bound evidence changed')
    work=Path(proof['restored_workspace'])
    actual={p.relative_to(work).as_posix():{'size':p.stat().st_size,'sha256':sha(p)} for p in work.rglob('*') if p.is_file()}
    if actual!=proof['task_inventory']: raise ValueError('restored workspace changed')
    output=Path(output)
    if output.exists(): raise ValueError('independent output already exists')
    n=proof['prefix_count'];flowkey=hashlib.sha256(row['flow_id'].encode()).hexdigest()[:10]
    dest=output/'_checkpoints'/flowkey/f't{n+1:04d}';dest.mkdir(parents=True)
    evolution={'completed':False,'events':[{'type':'evolution.proposal_rejected','original_error':proof['original_error'],'recovered_without_retry':True}],
        'usage':{},'usage_status':'unknown_original_failed_learning','state_before':proof['snapshot'],'state_after':proof['snapshot'],'changed_files':[]}
    final=pending[-1];record={'turn_id':proof['target'],'score':final['score'],'passed':final['passed'],
        'interactions':[{k:v for k,v in x.items() if k!='turn_id'} for x in pending], 'evolution':evolution,
        'recovered_bounded_evolution_failure':True,'independent_recovery_proof':str(output/'recovery-proof.json')}
    # Extra record metadata is stored in the proof, not the native TurnRecord
    # constructor. The evolution itself carries the full independent provenance.
    record.pop('recovered_bounded_evolution_failure');record.pop('independent_recovery_proof')
    evolution['independent_recovery']={k:proof[k] for k in ('schema','key','unknown_failed_learning_usage_preserved','native_remaining_counter_receipt_claimed','exact_post_failure_workspace_claimed','failed_learned_state_adopted')}
    records=copy.deepcopy(prefix)+[record]
    with zipfile.ZipFile(dest/'workspace.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(proof['task_inventory']):z.write(work/name,name)
    cp=Path(proof['original_checkpoint']);shutil.copyfile(cp/'baseline_state.zip',dest/'baseline_state.zip')
    meta=load(cp/'checkpoint.json');meta.update(completed_turn_index=n,next_turn_index=n+1,turn_id=proof['target'],token_budget=proof['derived_known_budget_lower_bound'],
        independent_recovery={'proof':str(output/'recovery-proof.json'),'key':proof['key'],'historical_unknown_usage':True,'budget_is_known_lower_bound':True,'post_failure_exact_continuation_claimed':False})
    for name,data in [('checkpoint.json',meta),('completed_turns.json',records)]: (dest/name).write_text(json.dumps(data,indent=2),encoding='utf-8')
    (output/'recovery-proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    _checkpoint_preserves_prefix({**row,'output':str(output)},dest,n+1)
    return {'checkpoint':str(dest),'output':str(output),'proof_key':proof['key'],'saved_score':1.0,'new_model_calls':0,'target':proof['target']}


def validate_adoption(row):
    path=Path(row['l1_rejected_learning_authorization'])
    if sha(path)!=row['l1_rejected_learning_authorization_sha256']: raise ValueError('L1 failure adoption authority changed')
    auth=load(path)
    if auth.get('output')!=row['output'] or auth.get('job')!=row['id'] or auth.get('schema')!=SCHEMA:
        raise ValueError('L1 failure adoption identity changed')
    proof=load(Path(row['output'])/'recovery-proof.json')
    original=auth['original_row'];fresh=inspect(original,proof['restoration_review'],proof['restored_workspace'],proof['authorization'])
    if fresh[0]!=proof or auth.get('proof_key')!=proof['key']: raise ValueError('L1 original failure evidence changed')
    for item in auth['initial_checkpoint_bindings'].values():
        if sha(item['path'])!=item['sha256']: raise ValueError('L1 initial restored checkpoint changed')
    return auth
