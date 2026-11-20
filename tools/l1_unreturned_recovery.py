"""Evidence-bound recovery of an L1 first Interaction that returned no reply.

This deliberately excludes saved replies, later Interactions and failed learning.
The caller must consume the shared one-shot ledger before dispatching the command.
"""
from pathlib import Path
import hashlib,json,re
from tools.run_new_package_matrix import (
    latest_checkpoint, report_for, _checkpoint_preserves_prefix, command,
)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def neutral_transport_error(error):
    """Exact empty-stream/service failures, never an authentication/content refusal."""
    if re.search(r'policy|content.?filter|被拦截|封禁|unauthorized|forbidden|insufficient_quota|(?:HTTP|code:)\s*(?:401|402|403)',error,re.I):
        return False
    if 'baseline adapter interact failed:' not in error:
        return False
    return (error.endswith('upstream Responses stream failed')
            or error.endswith('upstream Responses stream ended before completion')
            or error.endswith('OpenCode request failed: upstream transport timed out')
            or error.endswith('Prime Agent RPC absolute deadline expired during prompt')
            or bool(re.search(r'(?:Error code:|HTTP)\s*500\b.*upstream error: do request failed \(request id: [A-Za-z0-9_-]+\)$',error)))

def inspect_frontier(row):
    if row.get('level')!='l1' or row.get('condition')!='evolving':
        raise ValueError('only evolving L1 is supported')
    if row.get('status') not in ('paused_error','needs_attention','blocked_recovery'):
        raise ValueError('not a failed execution boundary')
    if report_for(row)[1] is not None:
        raise ValueError('already completed')
    output=Path(row['output']).resolve()
    flow=output/row['flow_id']
    if flow.parent!=output:raise ValueError('invalid flow path')
    trace=flow/'live_trace.jsonl'
    records=[json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not records or any(not isinstance(x,dict) for x in records):raise ValueError('missing trace')
    cp=latest_checkpoint(row);n=0
    bindings={'trace':{'path':str(trace),'sha256':digest(trace)}}
    if cp is not None:
        meta=json.loads((cp/'checkpoint.json').read_text())
        n=meta['next_turn_index']
        if type(n) is not int or not 0<=n<len(row['turns']):raise ValueError('invalid completed frontier')
        if meta.get('exact_baseline_state') is not True:raise ValueError('inexact baseline archive')
        _checkpoint_preserves_prefix(row,cp,n)
        for name in ('checkpoint.json','workspace.zip','baseline_state.zip','completed_turns.json'):
            bindings['checkpoint/'+name]={'path':str(cp/name),'sha256':digest(cp/name)}
    target=row['turns'][n]
    if any(x.get('turn_id') not in row['turns'][:n+1] for x in records):raise ValueError('trace extends beyond completed frontier')
    unfinished=[x for x in records if x.get('turn_id')==target]
    if len(unfinished)!=1 or unfinished[0].get('index')!=1:
        raise ValueError('requires exactly one unfinished first Interaction')
    record=unfinished[0]
    if any(record.get(k) for k in ('response','actions','tool_calls','events','state_update')):
        raise ValueError('returned reply cannot be replayed')
    details=record.get('verifier_details',{})
    if not isinstance(details,dict) or details.get('type')!='model_error':
        raise ValueError('not a model transport interruption')
    error=str(details.get('error',''))
    if re.search(r'policy|content.?filter|被拦截|封禁|(?:HTTP|code:)\s*(?:401|402|403)',error,re.I):
        raise ValueError('provider/content hold cannot be retried')
    transient=(bool(re.search(r'timed out during interact|Request timed out|502.*(?:ReadError|BrokenPipeError|RemoteProtocolError|ConnectError)|no upstream request sent',error))
               or neutral_transport_error(error)
               or bool(re.search(r'(?:HTTP|code:)\s*504\b.*upstream transport timed out|(?:HTTP|code:)\s*502\b.*本次请求出现异常，请稍后重试。',error))
               or row.get('agent')=='prime-agent' and 'Agent is already processing. Specify streamingBehavior' in error
               or row.get('agent')=='opencode' and error.endswith('OpenCode request failed: upstream transport timed out')
               or row.get('agent')=='codex' and 'stream closed before response.completed' in error)
    if not transient:raise ValueError('unclassified failure')
    logs=sorted(output.glob('driver-*.log'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not logs:raise ValueError('missing failed dispatcher log')
    text=logs[0].read_text(encoding='utf-8',errors='replace')
    if f'evaluation infrastructure failed in {target}:' not in text or error not in text:
        raise ValueError('failure log does not bind the trace frontier')
    bindings['driver']={'path':str(logs[0]),'sha256':digest(logs[0])}
    manifest=Path(row['package'])/'manifest.json'
    bindings['package_manifest']={'path':str(manifest),'sha256':digest(manifest)}
    flowkey=hashlib.sha256(row['flow_id'].encode()).hexdigest()[:10]
    advanced=output/'_checkpoints'/flowkey/f't{n+1:04d}'
    if advanced.exists():raise ValueError('target already has checkpoint evidence; do not replay')
    key=hashlib.sha256(json.dumps({'job':row['id'],'turn':target,'interaction':1},sort_keys=True).encode()).hexdigest()
    return {'job':row['id'],'key':key,'turn_id':target,'interaction_index':1,
            'prefix_count':n,'preserve_valid_turns':row['turns'][:n],
            'checkpoint':str(cp) if cp else None,'advanced_checkpoint':str(advanced),
            'bindings':bindings,'failure_category':'unreturned_first_interaction_transport_error',
            'failed_usage':'unknown; original failed request is not assumed free'}

def validate_bindings(proof):
    for item in proof['bindings'].values():
        if digest(item['path'])!=item['sha256']:raise ValueError('bound evidence changed')

def bounded_command(repo,row,branch_output,branch_checkpoint,config_dir,proof):
    if proof['job']!=row['id'] or row['turns'][proof['prefix_count']]!=proof['turn_id']:
        raise ValueError('job/frontier identity changed')
    partial={**row,'output':str(branch_output),'turns':row['turns'][:proof['prefix_count']+1]}
    # Preserve the original stream's aggregate token fuse as well as every
    # native Turn budget; bound only the selected execution suffix.
    argv=command(repo,{**row,'output':str(branch_output)},branch_checkpoint,config_dir)
    argv[argv.index('--turns')+1]=','.join(partial['turns'])
    if argv[argv.index('--turns')+1]!=','.join(partial['turns']):raise ValueError('bounded turn selection changed')
    return argv,partial

def consume_authorization(path,proof,argv):
    """One durable consume precedes Popen; changing evidence never consumes it."""
    import fcntl,os,time
    with Path(path).open('r+') as file:
        fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        auth=json.load(file)
        if auth.get('status')!='authorized_not_consumed' or auth.get('allowed_additional_attempts')!=1:
            raise ValueError('authorization already consumed or invalid')
        if auth.get('proof')!=proof:raise ValueError('authorization evidence mismatch')
        validate_bindings(proof)
        auth.update(status='consumed',consumed_at=time.time(),command=argv)
        file.seek(0);json.dump(auth,file,indent=2);file.truncate();file.flush();os.fsync(file.fileno())
