import json
import pytest
from baseline.adapters.codex.bridge import _encode_public_evolution_context, CodexError


def test_large_repeated_tool_outputs_are_preserved_exactly():
    text = '完整公开轨迹 / tool output\n' * 8000
    original = {'turn_id': 'turn2', 'trajectory': [{'request': 'unchanged',
        'tool_calls': [{'result': text, 'arguments': {'aggregated_output': text}}],
        'events': [{'output': text}]}], 'feedback': [{'score': 0, 'passed': False}]}
    packed = json.loads(_encode_public_evolution_context(original, lossless_dedup=True))
    assert len(json.dumps(packed, ensure_ascii=True)) < 1_000_000
    def restore(value):
        if isinstance(value, dict) and set(value) == {'$trievo_public_string_ref'}:
            return packed['strings'][value['$trievo_public_string_ref']]
        if isinstance(value, dict): return {k: restore(v) for k, v in value.items()}
        if isinstance(value, list): return [restore(x) for x in value]
        return value
    assert restore(packed['data']) == original


def test_default_and_small_context_encoding_is_unchanged():
    original = {'trajectory': [{'response': 'unchanged'}], 'feedback': []}
    for flag in (True, False):
        assert _encode_public_evolution_context(original, lossless_dedup=flag) == json.dumps(original, ensure_ascii=True)


def test_collision_fails_closed_instead_of_changing_user_data():
    with pytest.raises(CodexError, match='collision'):
        _encode_public_evolution_context({'$trievo_public_string_ref': 'original user key',
                                         'data': 'large' * 200000}, lossless_dedup=True)


def test_unique_public_evidence_is_never_truncated():
    original = {'response': 'x' * 1_100_000}
    assert json.loads(_encode_public_evolution_context(original, lossless_dedup=True)) == original


def test_line_encoding_preserves_every_character_and_nested_value():
    from baseline.adapters.codex.bridge import _encode_public_lines
    line = '公开 evidence\t' * 50 + '\r\n'
    original = {'response': line * 20 + 'unique尾\x00', 'nested': [True, None, 0, '', line + 'other\n']}
    packed = json.loads(_encode_public_lines(original))
    def restore(value):
        if isinstance(value, dict) and set(value) == {'$trievo_public_string_parts'}:
            return ''.join(packed['lines'][x] if type(x) is int else x
                           for x in value['$trievo_public_string_parts'])
        if isinstance(value, dict): return {k: restore(v) for k, v in value.items()}
        if isinstance(value, list): return [restore(x) for x in value]
        return value
    assert restore(packed['data']) == original
    assert line in packed['lines']


@pytest.mark.parametrize('key', ['$trievo_public_line_ref', '$trievo_public_string_parts'])
def test_line_reference_collision_fails_closed(key):
    from baseline.adapters.codex.bridge import _encode_public_lines
    with pytest.raises(CodexError, match='collision'):
        _encode_public_lines({'nested': [{key: 'literal user data'}]})


def test_line_fallback_is_opt_in_and_does_not_change_small_inputs():
    original = {'response': ('unique\r\n' + 'repeat line ' * 80 + '\n') * 2000}
    standard = _encode_public_evolution_context(original, lossless_dedup=True)
    improved = _encode_public_evolution_context(original, lossless_dedup=True, lossless_line_dedup=True)
    assert len(improved) < len(standard)
    assert 'lossless_public_line_interning_v1' in improved
    small = {'response': 'unchanged'}
    assert _encode_public_evolution_context(small, lossless_dedup=True, lossless_line_dedup=True) == json.dumps(small)
