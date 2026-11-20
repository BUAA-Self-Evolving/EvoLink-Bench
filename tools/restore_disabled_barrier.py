"""Restore only an unpaid disabled-evolution barrier from immutable native evidence."""
from pathlib import Path, PurePosixPath
import copy
import hashlib
import json
import math
import re
import shutil
import zipfile
import stat
from tools.finalize_l2_evolution_timeout import archive_inventory, snapshot_from_checkpoint, sha
from tools.run_new_package_matrix import _checkpoint_preserves_prefix, _report_matches_row, learning_continuity_prefix, completed_target_evidence, latest_checkpoint


def compare_workspace_archives(first: Path, second: Path, max_bytes: int = 512 * 1024**2) -> dict:
    """Audit large owned archives explicitly, with bounded streaming and exact equality."""
    if type(max_bytes) is not int or not 0 < max_bytes <= 4 * 1024**3:
        raise ValueError('workspace audit limit must be explicit and at most4GiB')
    summaries = []
    for path in (first, second):
        try:
            with zipfile.ZipFile(path) as archive:
                seen = set()
                total = 0
                for entry in archive.infolist():
                    part = PurePosixPath(entry.filename)
                    if (entry.filename in seen or part.is_absolute() or '..' in part.parts
                            or entry.orig_filename != entry.filename or '\\' in entry.filename
                            or entry.flag_bits & 1
                            or stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK):
                        raise ValueError('unsafe or duplicate workspace archive member')
                    seen.add(entry.filename)
                    total += entry.file_size
                    if total > max_bytes or len(seen) > 100000:
                        raise ValueError('workspace exceeds the selected separate audit limit')
                summaries.append({'declared_bytes': total, 'entries': len(seen), 'archive_sha256': sha(path)})
        except zipfile.BadZipFile as error:
            raise ValueError('invalid workspace zip') from error
    if summaries[0]['archive_sha256'] == summaries[1]['archive_sha256']:
        return {'equal': True, 'method': 'identical_compressed_archive_sha256', 'limit_bytes': max_bytes, 'archives': summaries}
    def inventory(path):
        result = {}
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                hasher = hashlib.sha256()
                with archive.open(entry) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        hasher.update(chunk)
                result[entry.filename] = (entry.file_size, hasher.hexdigest())
        return result
    return {'equal': inventory(first) == inventory(second), 'method': 'streamed_logical_file_sha256',
            'limit_bytes': max_bytes, 'archives': summaries}


def inspect_disabled(row: dict, report_path: Path, max_workspace_bytes: int = 512 * 1024**2) -> dict:
    """Require a terminal original Judge result plus unchanged native failure state."""
    if row.get('level') != 'l2' or row.get('condition') not in ('reset', 'frozen') or row.get('agent') != 'adaptive-auto-harness':
        raise ValueError('only disabled Adaptive L2 evolution is supported')
    if learning_continuity_prefix(row) is not None or row.get('status') not in ('paused_error', 'needs_attention', 'blocked_recovery'):
        raise ValueError('held, owned or complete job')
    p = report_path.resolve();output = Path(row['output']).resolve()
    if output not in p.parents:
        raise ValueError('foreign report')
    report = json.loads(p.read_text());error = str(report.get('error') or '')
    if not re.fullmatch(r'BaselineProtocolError: baseline adapter response id mismatch: expected [0-9]+, got None', error) or not report.get('finished_at'):
        raise ValueError('not the exact finished protocol barrier failure')
    n = len(report['turns']);clean = {**report, 'error': None, 'cleanup_error': None}
    if n >= len(row['turns']) or not _report_matches_row({**row, 'turns': row['turns'][:n]}, clean):
        raise ValueError('invalid original prefix')
    target = row['turns'][n]
    if completed_target_evidence(row, target) is not None:
        raise ValueError('target already completed in preserved evidence')
    pending = []
    for mp in (output / '_checkpoints').rglob('checkpoint.json'):
        m = json.loads(mp.read_text())
        if m.get('run_id') == report['run_id'] and m.get('turn_id') == target and m.get('phase') == 'adjudicate' and not m.get('invalidated'):
            pending.append((m['interaction_index'], mp.parent, m))
    if not pending:
        raise ValueError('missing final saved reply')
    k, cp, meta = max(pending)
    protected = latest_checkpoint(row)
    if protected is None or protected.resolve() != cp.resolve():
        raise ValueError('not the latest protected saved-reply frontier')
    _checkpoint_preserves_prefix(row, cp, n)
    if meta.get('learner_state_digest') != sha(cp / 'baseline_state.zip'):
        raise ValueError('learner archive changed')
    records = [json.loads(x) for x in (p.parent / 'trace.jsonl').read_text().splitlines() if x.strip()]
    if any(x.get('turn_id') == target and x.get('record_type') == 'evolution' for x in records):
        raise ValueError('barrier already has a completion record')
    finals = [x for x in records if x.get('turn_id') == target and x.get('interaction_index') == k and 'record_type' not in x]
    if len(finals) != 1:
        raise ValueError('terminal record not unique')
    final = finals[0];e = json.loads((cp / 'evidence.json').read_text());reply = e.get('reply', {})
    if final.get('response') != reply.get('text') or final.get('request') != e.get('request') or final.get('tool_calls', []) != reply.get('tool_calls', []):
        raise ValueError('paid reply binding mismatch')
    interactions = e.get('interactions', []) + [final]
    if [x.get('interaction_index') for x in interactions] != list(range(1, k + 1)):
        raise ValueError('missing earlier paid Interaction')
    if any(x.get('turn_id') != target or x.get('evaluation_status') == 'evaluation_error' or x.get('terminal_evaluation_error') for x in interactions):
        raise ValueError('unresolved Judge evidence')
    score = final.get('score');maximum = report['run_configuration']['execution_requirements']['max_interactions']
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1 or type(final.get('passed')) is not bool:
        raise ValueError('invalid original score')
    if not (final['passed'] or k == maximum or final.get('verifier', {}).get('category') == 'execution_limit'):
        raise ValueError('Interaction terminality not proven')
    exports = []
    roots = [p.parent / 'failed_evolution']
    if row['condition'] == 'reset':
        roots.append(p.parent / 'runtime_segments' / f't{n+1:04d}' / 'failed_evolution')
    for fp in [file for root in roots for file in root.glob('*/failure.json')]:
        f = json.loads(fp.read_text())
        if f.get('turn_id') == target and f.get('recoverable_checkpoint') is False:
            exports.append(fp)
    if len(exports) != 1:
        raise ValueError('missing exact failed-evolution invocation evidence')
    failed = exports[0].parent;snapshot = snapshot_from_checkpoint(cp / 'baseline_state.zip')
    native_snapshot = json.loads((failed / 'baseline_state_snapshot.json').read_text())
    if native_snapshot != snapshot or json.loads(exports[0].read_text()).get('state_digest') != snapshot['digest']:
        raise ValueError('native failed state differs from original saved state')
    original_files = archive_inventory(cp / 'baseline_state.zip');original_files.pop('.trievo_semantic_state.json', None)
    if archive_inventory(failed / 'baseline_state.zip') != original_files:
        raise ValueError('native declared state bytes differ')
    workspace_comparison = compare_workspace_archives(p.parent / 'error_workspace.zip', cp / 'workspace.zip', max_workspace_bytes)
    if not workspace_comparison['equal']:
        raise ValueError('workspace changed after the original Judge result')
    files = [p, p.parent / 'trace.jsonl', p.parent / 'error_workspace.zip', exports[0], failed / 'baseline_state_snapshot.json', failed / 'baseline_state.zip']
    files += [cp / name for name in ('checkpoint.json', 'evidence.json', 'completed_turns.json', 'workspace.zip', 'baseline_state.zip')]
    bindings = {str(x): sha(x) for x in files}
    key = hashlib.sha256(json.dumps({'job': row['id'], 'bindings': bindings}, sort_keys=True).encode()).hexdigest()
    return {'job': row['id'], 'key': key, 'run_id': report['run_id'], 'target': target, 'n': n, 'k': k,
            'report': str(p), 'checkpoint': str(cp), 'bindings': bindings, 'snapshot': snapshot,
            'score': score, 'passed': final['passed'], 'final': final, 'interactions': interactions,
            'original_error': error, 'condition': row['condition'], 'workspace_comparison': workspace_comparison}


def materialize(row: dict, proof: dict, native_receipt: dict, output: Path) -> dict:
    """Keep the original score and use only a real offline native skip result."""
    if native_receipt.get('network') != 'none' or native_receipt.get('model_calls') != 0 or native_receipt.get('job') != row['id'] or native_receipt.get('proof_key') != proof['key']:
        raise ValueError('offline native barrier receipt not bound')
    result = native_receipt.get('evolve_result', {})
    if result.get('completed') is not True or result.get('usage') != {} or result.get('events') != [{'type': 'evolution.skipped', 'reason': 'condition:' + row['condition']}]:
        raise ValueError('not an actual unpaid disabled native barrier completion')
    if native_receipt.get('state_unchanged') is not True or native_receipt.get('workspace_unchanged') is not True:
        raise ValueError('offline barrier changed state')
    for p, expected in proof['bindings'].items():
        if sha(p) != expected:
            raise ValueError('bound original evidence changed')
    original = json.loads(Path(proof['report']).read_text());report = copy.deepcopy(original)
    run_id = 'disabled-barrier-' + proof['key'][:24];run = output / row['flow_id'] / run_id;run.mkdir(parents=True, exist_ok=False)
    cp = Path(proof['checkpoint']);n = proof['n'];target = proof['target']
    checkpoint = output / '_checkpoints' / hashlib.sha256(row['flow_id'].encode()).hexdigest()[:10] / run_id[-8:] / f't{n+1:04d}'
    checkpoint.mkdir(parents=True)
    evolution = {'completed': True, 'events': result['events'] + [{'type': 'infrastructure.unpaid_barrier_restored', 'proof_key': proof['key']}],
                 'usage': {}, 'state_before': proof['snapshot'], 'state_after': proof['snapshot'], 'changed_files': []}
    trace = run / 'trace.jsonl';trace.write_bytes((Path(proof['report']).parent / 'trace.jsonl').read_bytes())
    with trace.open('a') as stream:
        stream.write('\n' + json.dumps({'record_type': 'evolution', 'turn_id': target, 'evolution': evolution}) + '\n')
    report.pop('error', None);report.pop('cleanup_error', None)
    report.update(run_id=run_id, stopped_after_turn=target, completed=False, evaluation_complete=True,
                  infrastructure_recovery={'type': 'unpaid_disabled_evolution_barrier_completion', 'source_report': proof['report'],
                                           'source_error': proof['original_error'], 'proof_key': proof['key'],
                                           'original_judge_score_preserved': True, 'additional_model_calls': 0,
                                           'learning_was_enabled': False, 'offline_native_receipt': native_receipt})
    report['turns'].append({'condition': row['condition'], 'stream_id': row['flow_id'], 'turn_id': target, 'turn_index': n+1,
                           'sequence_role': row.get('turn_roles', {}).get(target), 'turn_score': proof['score'],
                           'evaluation_status': proof['final']['evaluation_status'], 'passed': proof['passed'],
                           'final_score': proof['score'], 'final_category': proof['final'].get('verifier', {}).get('category', 'fail'),
                           'interaction_count': proof['k'], 'trace_file': str(trace), 'evolution': evolution,
                           'effective_work_limits': original['run_configuration']['effective_work_limits'],
                           'checkpoint': str(checkpoint), 'recovered_unpaid_disabled_barrier': True})
    for name in ('workspace.zip', 'baseline_state.zip'):
        shutil.copy2(cp / name, checkpoint / name)
    meta = json.loads((cp / 'checkpoint.json').read_text());meta.pop('phase', None);meta.pop('interaction_index', None)
    meta.update(run_id=run_id, completed_turn_index=n, next_turn_index=n+1, token_budget=original.get('token_budget', {}),
                recovery_type='unpaid_disabled_barrier_completion')
    (checkpoint / 'checkpoint.json').write_text(json.dumps(meta, indent=2))
    (checkpoint / 'completed_turns.json').write_text(json.dumps(report['turns'], indent=2))
    (run / 'report.json').write_text(json.dumps(report, indent=2));(run / 'recovery-proof.json').write_text(json.dumps(proof, indent=2))
    partial = {**row, 'output': str(output), 'turns': row['turns'][:n+1]}
    if not _report_matches_row(partial, report):
        raise ValueError('restored original-score report does not validate')
    _checkpoint_preserves_prefix(partial, checkpoint, n+1)
    return {'report': str(run / 'report.json'), 'checkpoint': str(checkpoint), 'completed_prefix_turns': n+1,
            'additional_model_calls': 0, 'original_score': proof['score'], 'original_passed': proof['passed']}
