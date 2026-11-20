"""Read-only score/transcript audit. Never dispatches or changes experiment evidence."""
from pathlib import Path
import hashlib,json,math
from tools.run_new_package_matrix import _report_matches_row,_checkpoint_preserves_prefix,_turn_score,learning_continuity_prefix

MANIFEST_SHA='1ef7cec5be70d2cd8ace3d6a0d31f96eee8c57399472ca9501651bd5d5f16421'

def load(p):return json.loads(Path(p).read_text())
def finite_score(value):return type(value) in (int,float) and math.isfinite(value) and 0<=value<=1

def signature(turns):
 return [(t.get('turn_id'),_turn_score(t),t.get('passed'),(t.get('evolution') or {}).get('completed')) for t in turns]

def select_evidence(row):
 candidates=[];issues=[];output=Path(row['output'])
 reports=output.glob('*/summary.json') if row['level']=='l1' else output.glob('*/*/report.json')
 for p in reports:
  try:
   report=load(p)
   if _report_matches_row(row,report):candidates.append((len(report['turns']),0,p.stat().st_mtime,p,report['turns'],None))
  except (OSError,ValueError,KeyError,TypeError):issues.append({'path':str(p),'issue':'unreadable_report'})
 # Each post-turn archive already embeds its entire cumulative prefix. Inspect
 # the greatest admissible prefix per run instead of rereading its old copies.
 grouped={};limit=learning_continuity_prefix(row)
 for p in output.glob('_checkpoints/**/completed_turns.json'):
  stem=p.parent.name
  if not stem.startswith('t') or not stem[1:].isdigit():continue
  n=int(stem[1:])
  if not 0<n<=len(row['turns']) or limit is not None and n>limit:continue
  key=p.parent.parent
  grouped.setdefault(key,[]).append((n,p))
 for same_run in grouped.values():
  for expected,p in sorted(same_run,key=lambda x:x[0],reverse=True):
   try:
    meta=load(p.parent/'checkpoint.json');turns=load(p);n=len(turns)
    if n!=expected or meta.get('invalidated') or meta.get('non_resumable') or meta.get('phase') in ('adjudicate','interact_started','reply_received'):continue
    _checkpoint_preserves_prefix(row,p.parent,n)
    candidates.append((n,1,p.stat().st_mtime,p,turns,meta));break
   except (OSError,ValueError,KeyError,TypeError):continue
 if not candidates:return [],None,None,issues
 n,kind,_,source,turns,meta=max(candidates,key=lambda x:x[:3])
 # An audit cannot select the better score from two conflicting histories.
 conflicts=[]
 selected=signature(turns)
 for count,_,_,p,other,_ in candidates:
  for i,(a,b) in enumerate(zip(selected,signature(other))):
   if a!=b:conflicts.append({'turn_index':i,'source':str(p)});break
 if conflicts:
  first=min(x['turn_index'] for x in conflicts)
  issues.append({'issue':'conflicting_completed_histories','valid_common_prefix':first,'conflicts':conflicts})
  turns=turns[:first]
 return turns,source,meta,issues

class TraceReader:
 def __init__(self):self.cache={}
 def read(self,p):
  p=Path(p);key=(str(p),p.stat().st_size,p.stat().st_mtime_ns)
  if p.stat().st_size>64*1024**2:raise ValueError('trace exceeds read-only audit size bound')
  if key not in self.cache:
   if len(self.cache)>=8:self.cache.pop(next(iter(self.cache)))
   self.cache[key]=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
  return self.cache[key]

def rehydrate_interactions(row,turn,records,trace):
 count=turn.get('interaction_count');indices=[x.get('interaction_index') for x in records]
 if type(count) is not int or not indices or any(type(x) is not int for x in indices) or len(set(indices))!=len(indices):return None,None
 if indices!=list(range(min(indices),count+1)):return None,None
 n=row['turns'].index(turn['turn_id']);run=Path(trace).parent.name;candidates=[]
 for p in (Path(row['output'])/'_checkpoints').glob(f'**/p{n:04d}-{count:02d}/checkpoint.json'):
  try:
   meta=load(p)
   if meta.get('run_id')==run:candidates.append(p.parent)
  except (OSError,ValueError):pass
 proof=Path(trace).parent/'recovery-proof.json'
 if proof.exists():
  try:
   data=load(proof);cp=Path(data['checkpoint'])
   if data.get('job')==row['id'] and data.get('turn_id')==turn['turn_id'] and data.get('bindings',{}).get(str(cp/'evidence.json'))==hashlib.sha256((cp/'evidence.json').read_bytes()).hexdigest():candidates.append(cp)
  except (OSError,ValueError,KeyError,TypeError):pass
 for cp in candidates:
  try:
   _checkpoint_preserves_prefix(row,cp,n);meta=load(cp/'checkpoint.json');e=load(cp/'evidence.json');final=records[-1]
   if meta.get('phase')!='adjudicate' or meta.get('turn_id')!=turn['turn_id'] or meta.get('interaction_index')!=count or e.get('turn_id')!=turn['turn_id'] or e.get('turn_index')!=n or e.get('interaction_index')!=count:continue
   if e.get('request')!=final.get('request') or e.get('reply',{}).get('text')!=final.get('response') or e.get('reply',{}).get('tool_calls',[])!=final.get('tool_calls',[]):continue
   prefix=e.get('interactions',[])
   if [x.get('interaction_index') for x in prefix]!=list(range(1,count)):continue
   if meta.get('learner_state_digest')!=hashlib.sha256((cp/'baseline_state.zip').read_bytes()).hexdigest():continue
   keys=('request','response','tool_calls','score','passed','evaluation_status')
   if any(any(old.get(k)!=new.get(k) for k in keys) for new in records[:-1] for old in prefix if old['interaction_index']==new['interaction_index']):continue
   combined=prefix+[final]
   if any(x.get('evaluation_status')=='evaluation_error' or x.get('turn_id')!=turn['turn_id'] for x in combined):continue
   return combined,{'checkpoint':str(cp),'evidence_sha256':hashlib.sha256((cp/'evidence.json').read_bytes()).hexdigest(),'method':'raw_suffix_with_exact_saved_adjudication_history'}
  except (OSError,ValueError,KeyError,TypeError):pass
 return None,None

def transcript_check(row,turn,source,reader):
 if row['level']=='l1':
  items=turn.get('interactions')
  if not isinstance(items,list) or not items:return {'verified':False,'issue':'missing_embedded_interaction_history'}
  if [x.get('index') for x in items]!=list(range(1,len(items)+1)):return {'verified':False,'issue':'invalid_interaction_sequence'}
  final=items[-1]
  ok=finite_score(final.get('score')) and math.isclose(final['score'],_turn_score(turn),abs_tol=1e-9) and final.get('passed')==turn.get('passed')
  native=all(any(isinstance(e,dict) and e.get('type')=='target.completed' and e.get('native_function_tools') is True for e in x.get('events',[])) for x in items)
  return {'verified':ok,'method':'embedded_checkpoint_or_report_history','native_function_tools':native,'interaction_count':len(items),**({} if ok else {'issue':'terminal_embedded_score_mismatch'})}
 path=Path(str(turn.get('trace_file','')))
 if not path.is_absolute():
  if source.name=='report.json':path=source.parent/path
  else:return {'verified':False,'issue':'relative_trace_without_original_run_binding'}
 try:
  records=reader.read(path)
 except (OSError,ValueError):return {'verified':False,'issue':'unreadable_trace','path':str(path)}
 selected=[x for x in records if x.get('turn_id')==turn['turn_id'] and 'record_type' not in x]
 count=turn.get('interaction_count')
 rehydrated=None
 if not selected or type(count) is not int or [x.get('interaction_index') for x in selected]!=list(range(1,count+1)):
  try:selected,rehydrated=rehydrate_interactions(row,turn,selected,path)
  except (OSError,ValueError,KeyError,TypeError):selected=None
  if selected is None:return {'verified':False,'issue':'incomplete_or_duplicate_interaction_trace','path':str(path)}
 final=selected[-1];score=_turn_score(turn);evo=turn.get('evolution') or {}
 expected_pass=bool(final.get('passed')) and evo.get('completed') is not False
 ok=finite_score(final.get('score')) and math.isclose(final['score'],score,abs_tol=1e-9) and final.get('evaluation_status')!='evaluation_error' and expected_pass==turn.get('passed')
 evolutions=[x for x in records if x.get('turn_id')==turn['turn_id'] and x.get('record_type')=='evolution']
 evo_match=any(x.get('evolution')==evo for x in evolutions)
 return {'verified':ok and evo_match,'method':'raw_trace_terminal_and_evolution','path':str(path),'interaction_count':count,'evolution_record_matches':evo_match,'saved_history_provenance':rehydrated,**({} if ok and evo_match else {'issue':'trace_score_pass_or_evolution_mismatch'})}

def learning_tags(turn):
 evo=turn.get('evolution') or {};before=evo.get('state_before') or {};after=evo.get('state_after') or {}
 events=evo.get('events') or []
 return {'completed':evo.get('completed'),'state_changed':bool(before.get('digest') and after.get('digest') and before['digest']!=after['digest']),
 'derived_bounded_failure':bool(turn.get('recovered_bounded_evolution_failure') or evo.get('independent_recovery',{}).get('schema') in ('trievo.independent-l1-rejected-learning.v1','trievo.independent-initial-l1-timeout.v1')),
 'unpaid_disabled_barrier_restoration':bool(turn.get('recovered_unpaid_disabled_barrier')),
 'session_continuity':any('session_continuity' in str(x) for x in events),
 'events':[str(x.get('type','unknown')) for x in events if isinstance(x,dict)]}
