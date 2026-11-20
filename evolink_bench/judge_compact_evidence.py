"""Exact, readable dictionary references for explicitly authorized input version 2.

This codec neither truncates evidence nor authorizes any model call. It retains
all JSON types, strings and object order and verifies an exact content commitment.
"""
from collections import Counter
import hashlib
import json

SCHEMA = 'trievo_exact_shared_values/2.0'
REF = '$v'
LITERAL = '$literal'

def serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

def encode(values):
    if type(values) is not dict:
        raise ValueError('expected JSON object')
    counts = Counter()
    active = set()
    def visit(value):
        if type(value) not in (dict, list, str, int, float, bool, type(None)):
            raise ValueError('non-JSON evidence')
        if isinstance(value, (dict, list)):
            if id(value) in active: raise ValueError('cyclic evidence')
            active.add(id(value))
            if isinstance(value, dict):
                if any(type(k) is not str for k in value): raise ValueError('non-string key')
                children = value.values()
            else: children = value
            for item in children: visit(item)
            active.remove(id(value))
        raw = serialized(value)
        if len(raw.encode()) >= 64: counts[raw] += 1
    visit(values)
    identifiers = {raw:i for i,raw in enumerate((k for k,n in counts.items() if n>1),1)}
    definitions = {}
    def pack(value, defining=None):
        raw = serialized(value); identifier = identifiers.get(raw)
        if identifier is not None and identifier != defining:
            key = str(identifier)
            if key not in definitions: definitions[key] = pack(value,identifier)
            return {REF:identifier}
        if isinstance(value,dict):
            if REF in value or LITERAL in value:
                return {LITERAL:[[k,pack(v)] for k,v in value.items()]}
            return {k:pack(v) for k,v in value.items()}
        if isinstance(value,list):return [pack(v) for v in value]
        return value
    original = serialized(values).encode()
    packet = {'schema':SCHEMA,'roots':{k:pack(v) for k,v in values.items()},
        'definitions':definitions,'original_utf8_bytes':len(original),
        'original_sha256':hashlib.sha256(original).hexdigest()}
    if serialized(decode(packet)).encode()!=original:raise ValueError('roundtrip mismatch')
    return packet

def decode(packet):
    if type(packet) is not dict or packet.get('schema') != SCHEMA:
        raise ValueError('unknown compact evidence schema')
    definitions=packet.get('definitions');roots=packet.get('roots')
    if type(definitions) is not dict or type(roots) is not dict:raise ValueError('invalid packet')
    active=set()
    def unpack(value):
        if isinstance(value,dict):
            if REF in value:
                n=value[REF]
                if set(value)!={REF} or type(n) is not int or n<1:raise ValueError('invalid reference')
                key=str(n)
                if key not in definitions or key in active:raise ValueError('missing or cyclic reference')
                active.add(key);out=unpack(definitions[key]);active.remove(key);return out
            if LITERAL in value:
                members=value[LITERAL]
                if set(value)!={LITERAL} or type(members) is not list or any(type(x) is not list or len(x)!=2 or type(x[0]) is not str for x in members):raise ValueError('invalid literal')
                if len({x[0] for x in members})!=len(members):raise ValueError('duplicate literal key')
                return {k:unpack(v) for k,v in members}
            return {k:unpack(v) for k,v in value.items()}
        if isinstance(value,list):return [unpack(v) for v in value]
        if type(value) not in (str,int,float,bool,type(None)):raise ValueError('non-JSON value')
        return value
    result={k:unpack(v) for k,v in roots.items()};raw=serialized(result).encode()
    if len(raw)!=packet.get('original_utf8_bytes') or hashlib.sha256(raw).hexdigest()!=packet.get('original_sha256'):raise ValueError('content commitment mismatch')
    return result
