"""Explicit independent adjudication of a saved, uncommitted RESET reply.

The original permission failure stays unchanged. A separately recorded offline
native verification is new evidence, and the historical budget is a lower bound.
This is intentionally separate from exact original native-result reuse.
"""
from pathlib import Path
import copy
import hashlib
import json

FILES = {'checkpoint.json', 'completed_turns.json', 'workspace.zip', 'baseline_state.zip', 'evidence.json'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(reference):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('invalid independent recovery reference')
    path = Path(reference['path'])
    if sha(path) != reference['sha256']:
        raise ValueError('independent recovery evidence changed')
    return json.loads(path.read_text())


def validate(reference, *, checkpoint, baseline, condition, stop_after_turn):
    a = load(reference)
    if (a.get('schema') != 'trievo.uncommitted-reset-permission-recovery.v1'
            or baseline != 'codex' or condition != 'reset'
            or a.get('baseline') != baseline or a.get('condition') != condition
            or stop_after_turn != a.get('turn') or a.get('interaction') != 1
            or a.get('agent_replays') != 0 or a.get('select_by_score') is not False
            or a.get('all_original_costs_retained') is not True
            or a.get('unknown_historical_usage') is not True):
        raise ValueError('not an independent single saved RESET reply recovery')
    cp = Path(checkpoint).resolve()
    if cp != Path(a['checkpoint']).resolve() or set(a['checkpoint_sha256']) != FILES:
        raise ValueError('wrong saved recovery checkpoint')
    for name, digest in a['checkpoint_sha256'].items():
        if sha(cp / name) != digest:
            raise ValueError('saved recovery checkpoint changed')
    m = json.loads((cp / 'checkpoint.json').read_text())
    e = json.loads((cp / 'evidence.json').read_text())
    if (m.get('phase') != 'adjudicate' or m.get('invalidated')
            or m.get('turn_id') != a['turn'] or m.get('baseline') != baseline
            or m.get('condition') != condition or m.get('interaction_index') != 1
            or e.get('turn_id') != a['turn'] or e.get('interaction_index') != 1
            or e.get('history') != [] or e.get('interactions') != []):
        raise ValueError('not the exact original first saved reply')
    projection = load(a['projection'])
    selected = [x for x in projection['placements'] if x['job'] == a['job']]
    if (len(selected) != m['next_turn_index'] or any(x['turn'] == a['turn'] for x in selected)
            or a['job'] != f"l2/reset/codex/{a['stream_key']}"):
        raise ValueError('target is already recorded or not the next missing RESET turn')
    user = load(a['user_authorization'])
    if user.get('extra_recovery_spend_authorized') is not True or user.get('valid_low_score_reruns_authorized') is not False:
        raise ValueError('repair spend authority missing')
    parents = load(a['parent_claims'])
    if not parents.get('claims'):
        raise ValueError('prior paid claim evidence missing')
    for parent in parents['claims']:
        if sha(parent['path']) != parent['sha256']:
            raise ValueError('historical paid claim changed')
    proof = load(a['native_proof'])
    if (proof.get('job') != a['job'] or proof.get('source_checkpoint') != str(cp)
            or proof.get('source_checkpoint_sha256') != a['checkpoint_sha256']
            or proof.get('source_task_sha256') != a['task']['sha256']
            or proof.get('original_saved_reply_exactly_matches_source_trace') is not True
            or proof.get('original_bf5e_reply_workspace_equal') is not True
            or proof.get('original_archives_and_workspace_unchanged') is not True
            or proof.get('network_none_observed') is not True
            or proof.get('agent_replays') != 0 or proof.get('judge_calls') != 0
            or proof.get('learning_calls') != 0 or proof.get('production_claims') != 0
            or proof.get('native_verifier_containers') != 1
            or not proof.get('cleanup_actual_inspect')
            or not all(v.get('absent') is True for v in proof['cleanup_actual_inspect'].values())):
        raise ValueError('no exact offline native repair proof')
    trace = load_text_reference(proof['original_trace'])
    records = [json.loads(x) for x in trace.splitlines() if x.strip()]
    records = [x for x in records if x.get('turn_id') == a['turn'] and x.get('interaction_index') == 1 and 'record_type' not in x]
    if len(records) != 1:
        raise ValueError('ambiguous original paid reply')
    raw = records[0]
    if (raw.get('response') != e['reply']['text'] or raw.get('tool_calls') != e['reply']['tool_calls']
            or raw.get('request') != e.get('request')):
        raise ValueError('original paid reply differs')
    original = raw.get('verifier', {}).get('native_result', {}).get('private_diagnostics', {})
    if (original.get('reason') != 'invalid_submission'
            or not str(original.get('error', '')).startswith("[Errno 13] Permission denied: '/workspace/")):
        raise ValueError('original result is not the proved permission fault')
    native = proof['native_result']
    if native.get('native_result', {}).get('status') != 'pass':
        raise ValueError('repaired native verification did not pass')
    accounting = load(a['historical_accounting'])
    floor = a['historical_known_lower_bound']
    if (floor != {'used': accounting['unique_historical_known_token_lower_bound'],
                  'calls': accounting['unique_historical_known_call_lower_bound']}
            or floor['used'] < m['token_budget']['used'] or floor['calls'] < m['token_budget']['calls']
            or a['token_limit'] != m['token_budget']['limit'] or floor['used'] >= a['token_limit']
            or accounting.get('unknown_later_failed_judge_tokens') is not True
            or accounting.get('current_59826747_failure_usage_not_included_as_zero') is not True):
        raise ValueError('historical failure costs omitted or original ceiling changed')
    return a


def load_text_reference(reference):
    if sha(reference['path']) != reference['sha256']:
        raise ValueError('original source trace changed')
    return Path(reference['path']).read_text()


def reuse(reference, *, checkpoint, baseline, condition, stop_after_turn, task, reply, workspace_inventory):
    a = validate(reference, checkpoint=checkpoint, baseline=baseline, condition=condition, stop_after_turn=stop_after_turn)
    e = json.loads((Path(checkpoint) / 'evidence.json').read_text())
    if (load(a['task']) != task or task['turn_id'] != a['turn']
            or reply.text != e['reply']['text'] or reply.tool_calls != e['reply']['tool_calls']
            or reply.usage.to_dict() != e['reply']['usage'] or workspace_inventory != a['workspace_inventory']):
        raise ValueError('repaired native task, saved reply or workspace differs')
    result = copy.deepcopy(load(a['native_proof'])['native_result'])
    result['independent_native_permission_recovery'] = {
        'authorization': reference, 'original_agent_replays': 0,
        'new_offline_native_proof': a['native_proof'], 'source_checkpoint': a['checkpoint'],
        'unknown_historical_usage': True, 'historical_known_lower_bound': a['historical_known_lower_bound'],
        'original_permission_result_preserved': True,
    }
    return result
