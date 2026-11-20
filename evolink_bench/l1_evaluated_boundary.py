"""Narrow independent Prime L1 evaluated-boundary recovery.

Retains the second original I1 and deterministic zero. Only the failed old
UserSimulator request and remaining Interactions execute. Historical usage
remains unknown; the separate public-default fuse is not an original counter.
"""
from pathlib import Path, PurePosixPath
import copy, hashlib, json, os, time, zipfile

JOB = 'l1/evolving/prime-agent/s02'
SCHEMA = 'trievo.prime-l1-evaluated-boundary.v1'
DIGEST = '296a85bb121aea74a9ec3c94b6fe34ea6dfd582f4a76eb2634c3219c49f8484c'
MODEL_SHA = 'a1ce06bb97019bc235232daf15d56a0de08b4bc710a367cb8896289b56c4752e'
IMAGE = 'sha256:287f7d1208df475247274f320ea7fae117fbfd23ace4ee00eb49ca3891312ebc'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(ref):
    if isinstance(ref, dict):
        if sha(ref['path']) != ref['sha256']: raise ValueError('bound authority/evidence changed')
        ref = ref['path']
    return json.loads(Path(ref).read_text(encoding='utf-8'))

def inventory(archive):
    result = {}
    with zipfile.ZipFile(archive) as z:
        for i in z.infolist():
            p = PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename:
                raise ValueError('unsafe original archive')
            if i.is_dir(): continue
            if i.filename in result: raise ValueError('duplicate archive entry')
            data = z.read(i)
            result[i.filename] = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
    return result

def task_inventory(snapshot):
    return {x['path'].removeprefix('/workspace/'): {'size':x['size'],'sha256':x['sha256']} for x in snapshot['files']}

def validate(ref, *, spec, flow, config, output, baseline, condition, limit):
    a = load(ref)
    required = {'original_agent_replays':0,'original_verifier_replays':0,'original_native_score':0,
                'selection_by_score':False,'original_native_session_exact':False,
                'historical_usage_unknown':True,'independent_fuse_is_original_ceiling':False,
                'unresolved_parent_claims':0,'selected_record_offset':1}
    if a.get('schema') != SCHEMA or a.get('job') != JOB or any(a.get(k) != v for k,v in required.items()):
        raise ValueError('independent evaluated-boundary authority required')
    if (baseline,condition,flow.id,Path(output).resolve(),limit) != ('prime-agent','evolving','l1_arena_stream_2',Path(a['output']).resolve(),3_000_000):
        raise ValueError('wrong recovery scope/output/fuse')
    if [t.id for t in flow.turns] != ['turn'+str(i) for i in range(1,19)]:
        raise ValueError('full original stream required')
    needed = [a[k] for k in ('original_trace','original_log','workspace_archive','state_archive','cli_source')]
    needed += [a['base_config']['path'],a['parent_review']['path'],a['user_authorization']['path']]
    if not all(p in a['bindings'] for p in needed): raise ValueError('missing original evidence bindings')
    parents=load(a['parent_review'])
    if parents.get('unresolved_production_claims')!=0 or parents.get('old_claims_reused') is not False:
        raise ValueError('parent claims not reconciled')
    for item in parents['references']:
        if sha(item['path'])!=item['sha256']: raise ValueError('parent evidence changed')
    for path,digest in a['bindings'].items():
        if sha(path) != digest: raise ValueError('original bound bytes changed: '+path)
    from tools.l1_initial_timeout import public_default_fuse
    if public_default_fuse(a['cli_source']) != limit: raise ValueError('separate public fuse changed')
    records = [json.loads(x) for x in Path(a['original_trace']).read_text().splitlines() if x.strip()]
    if len(records)!=2 or [x['index'] for x in records]!=[1,1] or records[0]['state_before']['digest']==DIGEST:
        raise ValueError('original distinct attempts changed')
    record = records[1]
    if (record['turn_id']!='turn1' or record['state_before']!={'digest':DIGEST,'files':['prime-home/models.json']}
        or record['score']!=0 or record['passed'] is not False or record['response']!=''
        or record['actions'] or record['tool_calls'] or record['state_update'] or record['action_error']
        or record['verifier_details'].get('type')!='l1_arena'
        or record['verifier_details']['verifier_results']['task']['returncode']!=1
        or record['sandbox']!=record['workspace_before']):
        raise ValueError('later original evaluated I1 identity differs')
    log = Path(a['original_log']).read_text()
    if 'HTTP 403' not in log or 'user.next_request' not in log:
        raise ValueError('not original failed old supplier UserSim')
    turn = flow.turns[0]
    if turn.request != record['request'] or turn.max_interactions!=3 or not turn.user.get('llm_post_failure'):
        raise ValueError('original request/simulator changed')
    if spec.agent != a['spec_agent'] or [t.metadata for t in flow.turns]!=a['turn_metadata']:
        raise ValueError('original agent limits changed')
    expected=task_inventory(record['sandbox'])
    if inventory(a['workspace_archive'])!=expected:
        raise ValueError('post-answer task bytes incomplete')
    if inventory(a['state_archive'])!={'prime-home/models.json':{'size':506,'sha256':MODEL_SHA}}:
        raise ValueError('original declared learner changed')
    base=load(a['base_config']);base.pop('type',None);base.pop('manifest',None);normalized=copy.deepcopy(config)
    option=normalized.get('options',{}).pop('l1_evaluated_boundary_recovery',None)
    if option != ref: raise ValueError('authority config differs')
    args=normalized['adapter']['command'];old=base['adapter']['command']
    if a.get('offline'):
        if len(args)==len(old)+1 and args[2]=='--network=none': args.pop(2)
        elif len(args)==len(old):
            for i,x in enumerate(args):
                if x=='--network' and args[i+1]=='none': args[i+1]=old[i+1]
                elif x=='--network=none' and old[i].startswith('--network='): args[i]=old[i]
    positions=[i for i,x in enumerate(args) if x==IMAGE]
    if len(positions)!=1: raise ValueError('reviewed compiled idle image required')
    args[positions[0]]=old[positions[0]]
    if normalized!=base: raise ValueError('unreviewed config or work limit changes')
    u=record['usage']
    if u.get('total_tokens')!=0 or u.get('api_calls')!=1:
        raise ValueError('original known usage record changed')
    return a,record

def claim(ref, a):
    p=Path(a['runtime_claim']);p.parent.mkdir(parents=True,exist_ok=True)
    value={'authorization':ref,'pid':os.getpid(),'time':time.time(),'first_paid_stage':'failed_UserSim_only',
           'first_agent_interaction':2,'original_I1_native_score':0,'original_I1_agent_verifier_replays':0,
           'historical_usage':'unknown','independent_fuse':3000000,'fuse_is_original_ceiling':False}
    with p.open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())


def verify_migrated_state(a, snapshot):
    files=snapshot.files
    if len(files)!=1 or files[0]['path']!='prime-home/models.json' or files[0]['sha256']!=a['migrated_models_sha256']:
        raise ValueError('only explicitly reviewed provider models migration is allowed')
    return snapshot.state


class BoundarySimulatorClient:
    """Durably bind the one failed-stage request before delegating to the client."""
    def __init__(self, client, authority, budget):
        self.client, self.authority, self.budget = client, authority, budget

    def complete(self, messages, **kwargs):
        p = Path(self.authority['runtime_claim']).parent / 'simulator-call-intent.json'
        value = {'messages':messages,'kwargs':kwargs,'known_budget_before':dict(vars(self.budget)),
                 'stage':'original_failed_UserSim','historical_usage_unknown':True}
        with p.open('x',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=True,indent=2);f.flush();os.fsync(f.fileno())
        result = self.client.complete(messages, **kwargs)
        receipt = {'response':result,'known_budget_after':dict(vars(self.budget)),
                   'intent_sha256':sha(p),'original_I1_agent_verifier_replays':0}
        with p.with_name('simulator-call-receipt.json').open('x',encoding='utf-8') as f:
            json.dump(receipt,f,ensure_ascii=True,indent=2);f.flush();os.fsync(f.fileno())
        return result
