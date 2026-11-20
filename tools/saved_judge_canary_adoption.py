"""Bind a single saved-Judge canary to normal full-matrix admission."""
from pathlib import Path
import copy,json,hashlib

FORMAL_SHA='1ef7cec5be70d2cd8ace3d6a0d31f96eee8c57399472ca9501651bd5d5f16421'
FIELD='saved_judge_single_canary'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate(row,reference,checkpoint=None):
 path=Path(reference['path'])
 if sha(path)!=reference['sha256']:raise ValueError('saved-Judge canary grant changed')
 g=json.loads(path.read_text());front=g['frontier']
 if (g.get('schema')!='exact_shared_saved_judge_canary/1.1' or g.get('scope_sha256')!=FORMAL_SHA
     or row.get('level')!='l2' or g.get('job')!=row['id'] or front.get('job')!=row['id']
     or g.get('condition')!=row.get('condition') or g.get('stop_after_turn')!=front.get('turn_id')
     or g.get('original_attempt_budgets_unchanged') is not True
     or g.get('original_paid_reply_not_replayed') is not True
     or g.get('all_original_costs_retained') is not True
     or g.get('input_representation_and_stateful_descendants_review_pending') is not True):
  raise ValueError('invalid single-target saved-Judge canary grant')
 cp=Path(front['checkpoint'])
 if checkpoint is not None and cp.resolve()!=Path(checkpoint).resolve():raise ValueError('saved-Judge checkpoint moved')
 if Path(row['output']).resolve() not in cp.resolve().parents:raise ValueError('saved-Judge output changed')
 required={'checkpoint.json','evidence.json','completed_turns.json','workspace.zip','baseline_state.zip'}
 if set(front['checkpoint_sha256'])!=required:raise ValueError('incomplete saved-Judge state binding')
 for name,digest in front['checkpoint_sha256'].items():
  if sha(cp/name)!=digest:raise ValueError('saved-Judge state changed')
 meta=json.loads((cp/'checkpoint.json').read_text());evidence=json.loads((cp/'evidence.json').read_text())
 if (meta.get('phase')!='adjudicate' or meta.get('turn_id')!=front['turn_id']
     or meta.get('interaction_index')!=front['interaction_index']
     or row['turns'][meta['next_turn_index']]!=front['turn_id']
     or evidence.get('turn_id')!=front['turn_id'] or evidence.get('interaction_index')!=front['interaction_index']
     or hashlib.sha256(json.dumps(evidence['reply'],sort_keys=True).encode()).hexdigest()!=front['reply_sha256']):
  raise ValueError('saved-Judge target or paid reply changed')
 for binding in [g['source_authorization'],g['full_launch_receipt'],g['original_config'],g['fixed_config'],g['input_map'],*g['parent_claims']]:
  if sha(binding['path'])!=binding['sha256']:raise ValueError('saved-Judge parent binding changed')
 if sha(front['report'])!=front['report_sha256']:raise ValueError('saved-Judge original fault changed')
 original=json.loads(Path(g['original_config']['path']).read_text());fixed=json.loads(Path(g['fixed_config']['path']).read_text())
 expected=copy.deepcopy(original);expected.setdefault('options',{})['l2_judge_shared_evidence_map']=g['input_map']
 if 'saved_native_verifier' in g:
  from evolink_bench.saved_native_verifier import load
  native=load(g['saved_native_verifier'])
  if (native.get('schema')!='trievo.saved-native-verifier/1.0' or native.get('checkpoint')!=str(cp)
      or native.get('turn_id')!=front['turn_id'] or native.get('condition')!=row['condition']):raise ValueError('canary saved native target changed')
  expected['options']['l2_saved_native_verifier']=g['saved_native_verifier']
 if original.get('options',{}).get('l2_judge_shared_evidence_map') or fixed!=expected:raise ValueError('canary config changed original budgets/options')
 mapping=json.loads(Path(g['input_map']['path']).read_text())
 entries=mapping.get('targets',[])
 if (mapping.get('schema')!='trievo_judge_input_map/1.1' or len(entries)!=1
     or entries[0].get('condition')!=row['condition'] or entries[0].get('turn_id')!=front['turn_id']
     or entries[0].get('interaction_index')!=front['interaction_index']):raise ValueError('canary input map target changed')
 grant=entries[0]['authorization']
 if sha(grant['path'])!=grant['sha256']:raise ValueError('canary input authorization changed')
 from tools.run_new_package_matrix import completed_target_evidence
 if completed_target_evidence(row,front['turn_id']) is not None:raise ValueError('canary target already completed; no reroll')
 return g

def apply(rows,root,path):
 mapping=json.loads(Path(path).read_text())
 if mapping.get('schema')!='trievo.saved-judge-single-canary/1.0' or len(mapping.get('entries',[]))!=1:raise ValueError('not a single canary map')
 entry=mapping['entries'][0];result=copy.deepcopy(rows);targets=[x for x in result if x['id']==entry['job']]
 if len(targets)!=1:raise ValueError('canary job absent or duplicated')
 row=targets[0]
 if Path(root).resolve() not in Path(row['output']).resolve().parents:raise ValueError('canary outside full matrix')
 validate(row,entry['authorization']);row[FIELD]=entry['authorization']
 return result

def bound_command(row,checkpoint,args):
 if FIELD not in row:return args
 g=validate(row,row[FIELD],checkpoint)
 if '--stop-after-turn' in args or '--retry-interrupted-run' in args:raise ValueError('overlapping canary/retry boundary')
 config_index=args.index('--baseline-config')+1
 if args[config_index]!=g['original_config']['path']:raise ValueError('canary original config differs from full command')
 result=list(args);result[config_index]=g['fixed_config']['path']
 insert=min((result.index(flag) for flag in ('--pool-id','--pool-manifest-sha256','--package-manifest-sha256','--runtime-profiles-sha256') if flag in result),default=len(result))
 result[insert:insert]=['--stop-after-turn',g['stop_after_turn']]
 if result!=g['native_command']:raise ValueError('canary native command or original budget changed')
 return result

def finished_report(row):
 """A bounded success is review-pending, never completion of the full stream."""
 try:
  reference=row[FIELD];path=Path(reference['path'])
  if sha(path)!=reference['sha256']:raise ValueError('completed canary grant changed')
  grant=json.loads(path.read_text())
  if grant['job']!=row['id'] or grant['condition']!=row['condition']:raise ValueError('completed canary identity changed')
  from tools.run_new_package_matrix import report_for_interrupted_retry
  return report_for_interrupted_retry(row,grant['stop_after_turn'])
 except (OSError,ValueError,KeyError) as error:
  row['saved_judge_canary_review_error']=str(error)
  return None,None

def restore_boundary(row,prior):
 """Width-only owner adoption must retain a pending/running canary contract."""
 if FIELD not in prior:return
 reference=prior[FIELD];path=Path(reference['path'])
 if sha(path)!=reference['sha256']:raise ValueError('adopted canary authorization changed')
 grant=json.loads(path.read_text())
 if (grant.get('schema')!='exact_shared_saved_judge_canary/1.1' or grant.get('job')!=row['id']
     or grant.get('condition')!=row['condition'] or grant.get('stop_after_turn')!=grant.get('frontier',{}).get('turn_id')):
  raise ValueError('adopted canary identity changed')
 if FIELD in row and row[FIELD]!=reference:raise ValueError('adopted canary contract replaced')
 row[FIELD]=copy.deepcopy(reference)
