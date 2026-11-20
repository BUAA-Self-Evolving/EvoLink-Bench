import copy,json,hashlib
import pytest
from evolink_bench.judge_compact_evidence import encode,decode,serialized,SCHEMA
from evolink_bench.judge_shared_evidence import render_candidate,render_bound_candidate,load_target_binding,SCHEMA as LEGACY
from evolink_bench.verifier import L1LifeJudge

def test_short_repeated_hashes_and_all_native_types_roundtrip():
    hashes={f'f/{i}':hashlib.sha256(str(i).encode()).hexdigest() for i in range(100)}
    v={'before':hashes,'after':{**hashes,'new':'a'*64},'types':[True,1,1.0,-0.0,None,'\x00\r\n中é  '],
       'literal':{'$v':1,'$literal':[['k','v']]},'again':{'$v':1,'$literal':[['k','v']]}}
    p=encode(v)
    assert serialized(decode(p))==serialized(v)
    assert len(serialized(p))<len(serialized(v))
    assert p['schema']==SCHEMA

@pytest.mark.parametrize('mutation',['missing','cycle','length','content','boolean_ref','literal_duplicate'])
def test_corruption_is_rejected(mutation):
    p=encode({'x':'x'*64,'y':'x'*64});key=str(p['roots']['x']['$v'])
    if mutation=='missing':del p['definitions'][key]
    if mutation=='cycle':p['definitions'][key]={'$v':int(key)}
    if mutation=='length':p['original_utf8_bytes']+=1
    if mutation=='content':p['definitions'][key]+='changed'
    if mutation=='boolean_ref':p['roots']['x']={'$v':True}
    if mutation=='literal_duplicate':p['roots']['x']={'$literal':[['a',1],['a',2]]}
    with pytest.raises(ValueError):decode(p)

def test_cycle_and_unsupported_data_rejected():
    x={};x['self']=x
    for v in (x,{1:'bad'},{'x':float('nan')},{'x':set()}):
        with pytest.raises((ValueError,TypeError)):encode(v)

def test_explicit_version_preserves_non_evidence_and_rejects_changed_input(tmp_path):
    values={'agent_input':{'q':'原问题'},'rubrics':{'unchanged':True},'tool_results':['x'*64]*3}
    render=L1LifeJudge._render;template='{agent_input}{rubrics}{tool_results}'
    old,_,oldproof=render_candidate(render,template,values)
    text,packet,proof=render_candidate(render,template,values,input_version=SCHEMA)
    assert oldproof['schema']==LEGACY and proof['schema']==SCHEMA and text!=old
    assert oldproof['non_evidence_sha256']==proof['non_evidence_sha256']
    assert oldproof['evidence_original_sha256']==proof['evidence_original_sha256']
    assert proof['exact_evidence_roundtrip'] and not proof['production_enabled']
    expected={k:v for k,v in proof.items() if k!='production_enabled'}
    def put(name,v):
        p=tmp_path/name;p.write_text(json.dumps(v));return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    grant={'baseline':'codex','condition':'frozen','stream_id':'s','turn_id':'t','interaction_index':2,'input_version':SCHEMA,
       'source_authorization':put('user.json',{'authorized':True}),'additional_agent_replays':0,'attempt_budgets_increased':False,'expected_proof':expected}
    auth=put('auth.json',grant);mapping=put('map.json',{'schema':'trievo_judge_input_map/1.1','input_version':SCHEMA,'baseline':'codex','targets':[{'condition':'frozen','stream_id':'s','turn_id':'t','interaction_index':2,'authorization':auth,'expected_proof':expected}]})
    binding=load_target_binding(mapping,baseline='codex',condition='frozen',stream_id='s',turn_id='t',interaction_index=2)
    bound,_,receipt=render_bound_candidate(render,template,values,binding)
    assert bound==text and receipt['production_enabled']
    for change in ('question','evidence','version'):
        v=copy.deepcopy(values);b=copy.deepcopy(binding)
        if change=='question':v['agent_input']['q']+='!'
        if change=='evidence':v['tool_results'].append('z')
        if change=='version':b['input_version']=LEGACY
        with pytest.raises(ValueError):render_bound_candidate(render,template,v,b)
