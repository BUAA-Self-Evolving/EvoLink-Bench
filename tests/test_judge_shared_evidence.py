import copy
import pytest
from evolink_bench.judge_shared_evidence import encode, decode, serialized, MARKER


def test_large_native_stdout_remains_complete_once():
    text = '完整原始输出\n' + ('price data line 0123456789\n' * 5000)
    original = {'tool_calls': [{'arguments': {'aggregated_output': text}, 'result': text}], 'tool_results': [text]}
    packet = encode(original)
    assert serialized(decode(packet)) == serialized(original)
    assert serialized(packet).count(text[:20].replace('\n', '\\n')) == 1
    assert len(serialized(packet)) < len(serialized(original)) / 2


def test_order_unicode_numeric_types_and_whitespace_are_exact():
    original = {'z': [{'b': -0.0, 'a': True}, {'b': -0.0, 'a': True}],
                'text': ['\u0000\r\n汉字é\t  ', '\u0000\r\n汉字é\t  '], 'null': None, 'number': 1}
    assert serialized(decode(encode(original, 1))) == serialized(original)


def test_literal_reference_markers_are_escaped():
    literal = {MARKER: 'ref', 'id': 'v1', 'nested': {MARKER: 'literal_object', 'members': []}}
    value = {'one': literal, 'two': copy.deepcopy(literal)}
    assert decode(encode(value, 1)) == value


def test_identical_before_after_inventories_share_whole_value():
    files = {f'dir/{i}/file.py': str(i).zfill(64) for i in range(2000)}
    packet = encode({'before': files, 'after': dict(files)})
    assert packet['roots']['before'] == packet['roots']['after']
    assert decode(packet)['before'] == files


@pytest.mark.parametrize('mutation', ['missing', 'cycle', 'content', 'length', 'schema'])
def test_tampering_fails_closed(mutation):
    p = encode({'a': 'long text' * 100, 'b': 'long text' * 100})
    key = p['roots']['a']['id']
    if mutation == 'missing': del p['definitions'][key]
    if mutation == 'cycle': p['definitions'][key] = {MARKER: 'ref', 'id': key}
    if mutation == 'content': p['definitions'][key] += 'changed'
    if mutation == 'length': p['original_utf8_bytes'] += 1
    if mutation == 'schema': p['schema'] = 'unknown'
    with pytest.raises(ValueError): decode(p)


@pytest.mark.parametrize('bad', [{1: 'non-string'}, {'nan': float('nan')}, {'set': {1, 2}}])
def test_non_json_values_are_rejected(bad):
    with pytest.raises((ValueError, TypeError)): encode(bad)


def test_cycle_is_rejected_before_serializing():
    value = {}; value['self'] = value
    with pytest.raises(ValueError): encode(value)


def test_render_candidate_keeps_question_and_rubric_outside_encoding():
    from evolink_bench.judge_shared_evidence import render_candidate
    values = {'agent_input': {'question': 'original question'}, 'rubrics': 'original rubric',
              'tool_calls': [{'result': 'full stdout\n' * 100}],
              'tool_results': ['full stdout\n' * 100]}
    captured = {}
    def render(template, given):
        captured.update(given)
        return template + serialized(given)
    text, packet, proof = render_candidate(render, 'immutable template', values)
    assert captured['agent_input'] is values['agent_input']
    assert captured['rubrics'] is values['rubrics']
    assert decode(packet)['tool_calls'] == values['tool_calls']
    assert proof['exact_evidence_roundtrip'] and not proof['production_enabled']
    assert 'immutable template' in text and 'original question' in text


def test_encoding_is_not_automatically_enabled_for_any_client():
    from evolink_bench.judge_shared_evidence import render_candidate
    text, packet, proof = render_candidate(lambda template, values: template, 'rubric', {'checks': []})
    assert packet['roots'] == {} and packet['definitions'] == {}
    assert proof['production_enabled'] is False
