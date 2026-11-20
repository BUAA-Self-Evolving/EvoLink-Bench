"""Reversible shared values for an explicitly versioned Judge-input candidate.

This module does not enable or send the representation. Every original JSON
value, string, character and key order can be reconstructed without external
files. The caller must separately authorize and disclose any production use.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

SCHEMA = 'trievo_exact_shared_values/1.0'
COMPACT_SCHEMA = 'trievo_exact_shared_values/2.0'
MARKER = '__trievo_shared_value__'
EVIDENCE_KEYS = ('interaction_transcript', 'tool_calls', 'tool_results',
                 'workspace_before', 'workspace_after', 'workspace_diff')


def serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def encode(values, minimum_bytes=512):
    if type(values) is not dict or type(minimum_bytes) is not int or minimum_bytes < 1:
        raise ValueError('expected a JSON object and positive byte threshold')
    counts = Counter()
    active = set()

    def visit(value):
        if type(value) not in (dict, list, str, int, float, bool, type(None)):
            raise ValueError('non-JSON evidence value')
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise ValueError('cyclic evidence')
            active.add(id(value))
            if isinstance(value, dict):
                if any(type(k) is not str for k in value):
                    raise ValueError('non-string object key')
                for v in value.values():
                    visit(v)
            else:
                for v in value:
                    visit(v)
            active.remove(id(value))
        raw = serialized(value)
        if len(raw.encode()) >= minimum_bytes:
            counts[raw] += 1

    visit(values)
    identifiers = {raw: 'v' + str(i) for i, raw in enumerate(
        (raw for raw in counts if counts[raw] > 1), 1)}
    definitions = {}

    def pack(value, defining=None):
        raw = serialized(value)
        identifier = identifiers.get(raw)
        if identifier is not None and identifier != defining:
            if identifier not in definitions:
                definitions[identifier] = pack(value, defining=identifier)
            return {MARKER: 'ref', 'id': identifier}
        if isinstance(value, dict):
            packed = {k: pack(v) for k, v in value.items()}
            # A literal marker is escaped; it can never be interpreted as a ref.
            if MARKER in value:
                return {MARKER: 'literal_object', 'members': [[k, pack(v)] for k, v in value.items()]}
            return packed
        if isinstance(value, list):
            return [pack(v) for v in value]
        return value

    roots = {k: pack(v) for k, v in values.items()}
    packet = {'schema': SCHEMA, 'roots': roots, 'definitions': definitions,
              'original_utf8_bytes': len(serialized(values).encode()),
              'original_sha256': hashlib.sha256(serialized(values).encode()).hexdigest()}
    # Fail before returning any representation that cannot recover exact JSON.
    if serialized(decode(packet)) != serialized(values):
        raise ValueError('shared evidence failed exact roundtrip')
    return packet


def decode(packet):
    if type(packet) is not dict or packet.get('schema') != SCHEMA:
        raise ValueError('unknown shared evidence schema')
    definitions = packet.get('definitions')
    if type(definitions) is not dict or type(packet.get('roots')) is not dict:
        raise ValueError('invalid shared evidence packet')
    active = set()

    def unpack(value):
        if isinstance(value, dict):
            if MARKER in value:
                if value[MARKER] == 'ref' and set(value) == {MARKER, 'id'}:
                    key = value['id']
                    if type(key) is not str or key not in definitions or key in active:
                        raise ValueError('missing or cyclic shared reference')
                    active.add(key)
                    result = unpack(definitions[key])
                    active.remove(key)
                    return result
                if value[MARKER] == 'literal_object' and set(value) == {MARKER, 'members'}:
                    members = value['members']
                    if type(members) is not list or any(type(x) is not list or len(x) != 2 or type(x[0]) is not str for x in members):
                        raise ValueError('invalid literal object')
                    if len({x[0] for x in members}) != len(members):
                        raise ValueError('duplicate literal object key')
                    return {k: unpack(v) for k, v in members}
                raise ValueError('invalid shared reference marker')
            return {k: unpack(v) for k, v in value.items()}
        if isinstance(value, list):
            return [unpack(v) for v in value]
        return value

    result = {k: unpack(v) for k, v in packet['roots'].items()}
    raw = serialized(result).encode()
    if len(raw) != packet.get('original_utf8_bytes') or hashlib.sha256(raw).hexdigest() != packet.get('original_sha256'):
        raise ValueError('shared evidence content commitment mismatch')
    return result


def render_candidate(render, template, values, *, input_version=SCHEMA):
    """Return an offline candidate and its proof; never enable a client or retry.

    Question, rubric, score schema, and every non-evidence value are passed to
    the original renderer unchanged. This is an input version, not a claim
    that an LLM will assign the same score to both representations.
    """
    forest = {k: values[k] for k in EVIDENCE_KEYS if k in values}
    if input_version == SCHEMA:
        packet = encode(forest)
        unpack = decode
    elif input_version == COMPACT_SCHEMA:
        from .judge_compact_evidence import encode as compact_encode, decode as unpack
        packet = compact_encode(forest)
    else:
        raise ValueError('unsupported evidence input version')
    replaced = {**values, **packet['roots']}
    text = render(template, replaced)
    if input_version == COMPACT_SCHEMA:
        text += ('\n[EXACT SHARED EVIDENCE FORMAT 2]\n'
                 'An object with exactly one key $v and an integer value refers to '
                 'the definition with that decimal id below. Recursively substitute '
                 'the exact JSON value. An object with exactly one key $literal '
                 'is an escaped original object: reconstruct its ordered [key,value] '
                 'members. Every original string, character, number, type and key order '
                 'is retained; no omitted evidence or external file is required.\n')
    else:
        text += ('\n[EXACT SHARED EVIDENCE FORMAT]\n'
             'Objects with __trievo_shared_value__=ref refer to the definition '
             'with the same id below. Recursively substitute references to '
             'recover each original JSON value. A literal_object preserves '
             'its members in order. Every original string and character is '
             'present; no external file or omitted evidence is required.\n')
    text += json.dumps({'schema': packet['schema'],
                        'definitions': packet['definitions']}, ensure_ascii=False)
    proof = {'schema': input_version, 'template_sha256': hashlib.sha256(template.encode()).hexdigest(),
             'non_evidence_sha256': hashlib.sha256(serialized(
                 {k: v for k, v in values.items() if k not in EVIDENCE_KEYS}).encode()).hexdigest(),
             'evidence_original_sha256': packet['original_sha256'],
             'candidate_sha256': hashlib.sha256(text.encode()).hexdigest(),
             'exact_evidence_roundtrip': serialized(unpack(packet)) == serialized(forest),
             'production_enabled': False}
    return text, packet, proof


def load_target_binding(reference, *, baseline, condition, stream_id, turn_id, interaction_index):
    """Load a hashed, separately authorized input version for one exact target.

    This does not reserve a Judge claim, resume a job, or authorize a dispatch.
    Owner fencing, paid-reply provenance and admission remain the caller's job.
    An absent target uses the ordinary representation; an invalid map fails.
    """
    if reference is None:
        return None
    if type(reference) is not dict or set(reference) != {'path', 'sha256'}:
        raise ValueError('invalid shared evidence map reference')
    path = Path(reference['path'])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('shared evidence map digest mismatch')
    data = json.loads(raw)
    if data.get('schema') != 'trievo_judge_input_map/1.1' or data.get('input_version') not in (SCHEMA, COMPACT_SCHEMA):
        raise ValueError('unsupported Judge input map')
    if baseline != 'codex' or data.get('baseline') != baseline:
        raise ValueError('shared evidence map baseline mismatch')
    targets = data.get('targets')
    if type(targets) is not list:
        raise ValueError('invalid Judge input targets')
    if any(type(x) is not dict or x.get('condition') not in ('reset', 'frozen', 'evolving')
           or type(x.get('stream_id')) is not str or not x['stream_id']
           or type(x.get('turn_id')) is not str or not x['turn_id']
           or type(x.get('interaction_index')) is not int or x['interaction_index'] < 1
           for x in targets):
        raise ValueError('invalid Judge input target identity')
    identities = [(x.get('condition'), x.get('stream_id'), x.get('turn_id'), x.get('interaction_index'))
                  for x in targets if type(x) is dict]
    if len(identities) != len(targets) or len(set(identities)) != len(identities):
        raise ValueError('duplicate or invalid Judge input targets')
    target = next((x for x in targets if (x['condition'], x['stream_id'], x['turn_id'], x['interaction_index']) ==
                   (condition, stream_id, turn_id, interaction_index)), None)
    if target is None:
        return None
    if type(target['interaction_index']) is not int or target['interaction_index'] < 1:
        raise ValueError('invalid Judge input Interaction')
    authorization = target.get('authorization')
    if type(authorization) is not dict or set(authorization) != {'path', 'sha256'}:
        raise ValueError('missing input-version authorization')
    grant_raw = Path(authorization['path']).read_bytes()
    if hashlib.sha256(grant_raw).hexdigest() != authorization['sha256']:
        raise ValueError('input-version authorization digest mismatch')
    grant = json.loads(grant_raw)
    source = grant.get('source_authorization')
    if type(source) is not dict or set(source) != {'path', 'sha256'}:
        raise ValueError('missing source authorization commitment')
    if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('source authorization digest mismatch')
    identity = {'baseline': baseline, 'condition': condition, 'stream_id': stream_id,
                'turn_id': turn_id, 'interaction_index': interaction_index,
                'input_version': data['input_version']}
    if any(grant.get(k) != v for k, v in identity.items()):
        raise ValueError('input-version authorization target mismatch')
    if grant.get('additional_agent_replays') != 0 or grant.get('attempt_budgets_increased') is not False:
        raise ValueError('input version cannot add Agent work or budgets')
    expected = target.get('expected_proof')
    if type(expected) is not dict or expected != grant.get('expected_proof'):
        raise ValueError('input-version proof differs from authorization')
    return {'expected_proof': expected, 'input_version': data['input_version'], 'map': reference,
            'authorization': authorization, 'target': identity}


def render_bound_candidate(render, template, values, binding):
    """Fail before a client call if the approved input differs by one byte."""
    text, packet, proof = render_candidate(render, template, values,
        input_version=binding.get('input_version', SCHEMA))
    keys = ('schema', 'template_sha256', 'non_evidence_sha256',
            'evidence_original_sha256', 'candidate_sha256', 'exact_evidence_roundtrip')
    actual = {k: proof[k] for k in keys}
    if binding.get('expected_proof') != actual:
        raise ValueError('current Judge input differs from bound representation')
    return text, packet, {**proof, 'production_enabled': True,
                          'map': binding['map'], 'authorization': binding['authorization'],
                          'target': binding['target']}


def retain_input_receipt(directory, proof):
    """Persist the validated input commitment before the first client dispatch."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw = serialized(proof).encode()
    path = directory / (hashlib.sha256(raw).hexdigest() + '.json')
    try:
        with path.open('xb') as stream:
            path.chmod(0o600)
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('input version receipt changed')
    return path


def input_version_lineage(completed_turns, interactions, *, reset):
    """Keep representation changes visible in later stateful Turn analysis."""
    versions = [] if reset else [v for t in completed_turns
                                for v in t.get('judge_input_version_lineage', [])]
    versions += [x['verifier']['judge']['details']['judge_input_version']
                 for x in interactions if x.get('verifier', {}).get('judge', {}).get(
                     'details', {}).get('judge_input_version') is not None]
    unique = {}
    for version in versions:
        unique.setdefault(serialized(version), version)
    return list(unique.values())
