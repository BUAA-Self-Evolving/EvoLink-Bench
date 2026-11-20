"""Explicit exact-byte reuse of a completed native verification, never Agent replay."""
from pathlib import Path
import copy,hashlib,json

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for data in iter(lambda:f.read(1024**2),b''):h.update(data)
 return h.hexdigest()

def load(reference):
 if not isinstance(reference,dict) or set(reference)!={'path','sha256'}:raise ValueError('invalid saved native reference')
 p=Path(reference['path'])
 if sha(p)!=reference['sha256']:raise ValueError('saved native binding changed')
 return json.loads(p.read_text())

def reuse(reference,*,checkpoint,baseline,condition,task,reply,workspace_inventory):
 """Fail closed unless source/current full paid state and artifact are bound."""
 g=load(reference)
 if g.get('schema')!='trievo.saved-native-verifier/1.0':raise ValueError('invalid saved native version')
 identity={'baseline':baseline,'condition':condition,'stream_id':task['stream_id'],'turn_id':task['turn_id']}
 if any(g.get(k)!=v for k,v in identity.items()):raise ValueError('saved native target changed')
 cp=Path(checkpoint).resolve()
 if cp!=Path(g['checkpoint']).resolve():raise ValueError('saved native checkpoint changed')
 required={'checkpoint.json','evidence.json','completed_turns.json','workspace.zip','baseline_state.zip'}
 if set(g['checkpoint_sha256'])!=required:raise ValueError('incomplete saved native state')
 for name,digest in g['checkpoint_sha256'].items():
  if sha(cp/name)!=digest:raise ValueError('saved native state changed')
 source=Path(g['source_checkpoint'])
 if set(g['source_checkpoint_sha256'])!=required:raise ValueError('incomplete native source state')
 for name,digest in g['source_checkpoint_sha256'].items():
  if sha(source/name)!=digest:raise ValueError('saved native source changed')
 meta=json.loads((cp/'checkpoint.json').read_text());e=json.loads((cp/'evidence.json').read_text())
 if (meta.get('phase')!='adjudicate' or meta.get('interaction_index')!=g['interaction_index']
     or e.get('interaction_index')!=g['interaction_index'] or e.get('turn_id')!=task['turn_id']
     or meta.get('turn_id')!=task['turn_id']):raise ValueError('not the original saved adjudication')
 if json.loads((source/'evidence.json').read_text())!=e:raise ValueError('source/current paid evidence differ')
 if json.loads((source/'completed_turns.json').read_text())!=json.loads((cp/'completed_turns.json').read_text()):raise ValueError('source/current full prefix differ')
 source_meta=json.loads((source/'checkpoint.json').read_text())
 for key in ('phase','baseline','condition','stream_id','turn_id','interaction_index','next_turn_index','token_budget'):
  if source_meta.get(key)!=meta.get(key):raise ValueError('source/current native state or budget differs')
 if (reply.text!=e['reply']['text'] or reply.tool_calls!=e['reply']['tool_calls']
     or reply.usage.to_dict()!=e['reply']['usage']):raise ValueError('saved native reply changed')
 for key in ('source_authorization','equivalence_audit','task'):
  load(g[key])
 if load(g['task'])!=task:raise ValueError('saved native task changed')
 audit=load(g['equivalence_audit'])
 if audit.get('source_checkpoint')!=str(source) or audit.get('checkpoint')!=str(cp):raise ValueError('native equivalence audit target changed')
 if audit.get('workspace_and_learner_equal') is not True or audit.get('remaining_budget_equal') is not True:raise ValueError('native state equivalence unproven')
 if workspace_inventory!=g['workspace_inventory']:raise ValueError('saved native workspace content changed')
 trace=Path(g['source_trace']['path'])
 if sha(trace)!=g['source_trace']['sha256']:raise ValueError('saved native trace changed')
 records=[json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
 matches=[x for x in records if x.get('turn_id')==task['turn_id'] and x.get('interaction_index')==g['interaction_index'] and 'record_type' not in x]
 if len(matches)!=1:raise ValueError('ambiguous saved native source')
 record=matches[0]
 if record.get('response')!=reply.text or record.get('tool_calls')!=reply.tool_calls:raise ValueError('native source reply differs')
 result=record['verifier']
 if result!=g['verification'] or result.get('category')=='error' or not isinstance(result.get('native_result'),dict):raise ValueError('saved native result changed or invalid')
 diagnostics=result['native_result'].get('private_diagnostics',{})
 if 'Permission denied' in str(diagnostics.get('error','')):raise ValueError('cannot reuse permission-polluted native result')
 result=copy.deepcopy(result)
 result['saved_native_verifier_provenance']={'schema':g['schema'],'authorization':reference,'source_trace':g['source_trace'],'source_checkpoint':str(source),'checkpoint':str(cp),'all_native_result_fields_preserved':True,'agent_replays':0}
 if 'judge_error' in result:
  result['saved_native_verifier_provenance']['source_judge_error']=result.pop('judge_error')
 return result
