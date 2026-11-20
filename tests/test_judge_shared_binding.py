import copy
import hashlib
import json
import pytest
from evolink_bench.judge_shared_evidence import (SCHEMA, load_target_binding,
                                               render_candidate, render_bound_candidate)
from evolink_bench.verifier import L1LifeJudge


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def prepared(tmp_path):
    values = {'tool_calls': [{'result': 'complete stdout' * 100}],
              'tool_results': ['complete stdout' * 100], 'agent_input': 'original question'}
    _, _, proof = render_candidate(L1LifeJudge._render, '{tool_calls}{agent_input}', values)
    proof.pop('production_enabled')
    grant = {'baseline': 'codex', 'condition': 'frozen', 'stream_id': 's', 'turn_id': 't', 'interaction_index': 2,
             'input_version': SCHEMA, 'additional_agent_replays': 0,
             'attempt_budgets_increased': False, 'expected_proof': proof,
             'source_authorization': write_json(tmp_path / 'source.json', {'authorization': 'test fixture'})}
    authorization = write_json(tmp_path / 'grant.json', grant)
    data = {'schema': 'trievo_judge_input_map/1.1', 'input_version': SCHEMA, 'baseline': 'codex',
            'targets': [{'condition': 'frozen', 'stream_id': 's', 'turn_id': 't', 'interaction_index': 2,
                         'authorization': authorization, 'expected_proof': proof}]}
    reference = write_json(tmp_path / 'map.json', data)
    return reference, data, grant, values


def load(reference, **overrides):
    return load_target_binding(reference, **({'baseline': 'codex', 'condition': 'frozen', 'stream_id': 's',
                                            'turn_id': 't', 'interaction_index': 2} | overrides))


def test_hashed_exact_target_roundtrip(prepared):
    reference, _, _, values = prepared
    text, _, proof = render_bound_candidate(L1LifeJudge._render, '{tool_calls}{agent_input}', values, load(reference))
    assert proof['production_enabled'] and proof['map'] == reference
    assert proof['exact_evidence_roundtrip'] and 'original question' in text


@pytest.mark.parametrize('target', [{'stream_id': 'other'}, {'turn_id': 'next'}, {'interaction_index': 3}, {'condition': 'reset'}])
def test_other_targets_keep_default_representation(prepared, target):
    assert load(prepared[0], **target) is None


def test_no_reference_keeps_default():
    assert load(None) is None


@pytest.mark.parametrize('fault', ['map_digest', 'grant_digest', 'grant_target', 'grant_budget',
                                   'grant_agent_replay', 'proof', 'duplicate', 'baseline', 'source_digest'])
def test_invalid_authority_fails_before_render_or_client(prepared, tmp_path, fault):
    reference, data, grant, _ = prepared
    if fault == 'map_digest': reference['sha256'] = '0' * 64
    elif fault == 'baseline': data['baseline'] = 'other'
    elif fault == 'duplicate': data['targets'] *= 2
    elif fault == 'proof': data['targets'][0]['expected_proof'] = {}
    elif fault == 'grant_digest': data['targets'][0]['authorization']['sha256'] = '0' * 64
    else:
        if fault == 'grant_target': grant['turn_id'] = 'wrong'
        if fault == 'grant_budget': grant['attempt_budgets_increased'] = True
        if fault == 'grant_agent_replay': grant['additional_agent_replays'] = 1
        if fault == 'source_digest': grant['source_authorization']['sha256'] = '0' * 64
        data['targets'][0]['authorization'] = write_json(tmp_path / 'grant.json', grant)
    if fault != 'map_digest': reference = write_json(tmp_path / 'map.json', data)
    with pytest.raises(ValueError): load(reference)


@pytest.mark.parametrize('changed', ['question', 'stdout', 'template'])
def test_changed_current_input_fails_closed(prepared, changed):
    reference, _, _, values = prepared
    values = copy.deepcopy(values); template = '{tool_calls}{agent_input}'
    if changed == 'question': values['agent_input'] += ' changed'
    if changed == 'stdout': values['tool_calls'][0]['result'] += ' changed'
    if changed == 'template': template += ' changed'
    with pytest.raises(ValueError): render_bound_candidate(L1LifeJudge._render, template, values, load(reference))


def test_real_judge_path_preserves_low_score_and_existing_retry_limit(monkeypatch, tmp_path):
    calls = []
    class Client:
        def complete(self, messages, **options):
            calls.append((messages, options))
            return json.dumps({'stream_id': 's', 'turn_id': 't',
                               'check_scores': [{'check_id': 'c', 'score': 0}],
                               'source_rubric_scores': []})
    check = {'stream_id': 's', 'turn_id': 't', 'judge_prompt': '{tool_calls}{agent_input}',
             'agent_input': 'original question', 'checks': [{'check_id': 'c', 'weight': 1}],
             'max_output_tokens': 4096}
    trajectory = {'tool_calls': [{'result': 'original stdout' * 100}],
                  'tool_results': ['original stdout' * 100]}
    original_render = L1LifeJudge._render; captured = {}
    def capture(template, values):
        captured.update(values)
        return original_render(template, values)
    monkeypatch.setattr(L1LifeJudge, '_render', staticmethod(capture))
    default = L1LifeJudge(Client()).evaluate(check, 'paid answer', None, trajectory)
    monkeypatch.setattr(L1LifeJudge, '_render', staticmethod(original_render))
    _, _, proof = render_candidate(original_render, check['judge_prompt'], captured)
    proof.pop('production_enabled')
    binding = {'expected_proof': proof, 'map': {'sha256': 'map'},
               'authorization': {'sha256': 'grant'}, 'target': {'turn_id': 't'},
               'receipt_directory': str(tmp_path)}
    result = L1LifeJudge(Client(), evidence_binding=binding).evaluate(check, 'paid answer', None, trajectory)
    assert result.score == default.score == 0 and result.passed is False
    assert len(calls) == 2  # One original, one candidate; valid zero does not retry.
    assert calls[0][1] == calls[1][1] == {'max_tokens': 4096, 'json_mode': True}
    assert calls[0][0][0] == calls[1][0][0]
    assert result.details['judge_input_version']['map']['sha256'] == 'map'
    assert len(list(tmp_path.glob('*.json'))) == 1
    class FailedClient:
        def complete(self, *args, **kwargs):
            assert len(list(tmp_path.glob('*.json'))) == 1
            raise RuntimeError('original HTTP 502')
    with pytest.raises(RuntimeError, match='original HTTP 502'):
        L1LifeJudge(FailedClient(), evidence_binding=binding).evaluate(check, 'paid answer', None, trajectory)
    assert len(list(tmp_path.glob('*.json'))) == 1
    binding['expected_proof'] = {}
    with pytest.raises(ValueError):
        L1LifeJudge(Client(), evidence_binding=binding).evaluate(check, 'paid answer', None, trajectory)
    assert len(calls) == 2  # Mismatched byte commitments never dispatch or fallback.


@pytest.mark.parametrize('reset', [False, True])
def test_representation_lineage_propagates_only_across_stateful_turns(reset):
    from evolink_bench.judge_shared_evidence import input_version_lineage
    first = {'candidate_sha256': 'first'}; second = {'candidate_sha256': 'second'}
    prior = [{'judge_input_version_lineage': [first, first]}]
    current = [{'verifier': {'judge': {'details': {'judge_input_version': second}}}}]
    assert input_version_lineage(prior, current, reset=reset) == ([second] if reset else [first, second])
    assert input_version_lineage(prior, [], reset=reset) == ([] if reset else [first])
