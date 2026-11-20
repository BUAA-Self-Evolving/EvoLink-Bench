from pathlib import Path
import importlib.util
import pytest
p=Path(__file__).resolve().parents[1]/'baseline/adapters/prime_agent/patch_rpc_idle_barrier.py'
spec=importlib.util.spec_from_file_location('prime_idle_patch',p);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

def test_native_idle_patch_is_opt_in_and_idempotent(tmp_path):
 p=tmp_path/'rpc.ts';p.write_text('prefix\n'+v.OLD+'\nsuffix')
 assert v.patch(p)['status']=='applied'
 s=p.read_text();assert 'trievoWaitForIdle === true' in s and 'await connection.waitForIdle()' in s
 assert 'const state = await connection.getState();' in s
 assert v.patch(p)['status']=='already_applied'

@pytest.mark.parametrize('s',['foreign source',v.OLD+'\n'+v.OLD])
def test_changed_vendor_source_fails_closed_without_edit(tmp_path,s):
 p=tmp_path/'rpc.ts';p.write_text(s)
 with pytest.raises(ValueError,match='refuse ambiguous'):v.patch(p)
 assert p.read_text()==s

def test_compiled_rpc_entrypoint_receives_opt_in_barrier(tmp_path):
 p=tmp_path/'rpc.js';original='case "get_state": {\n  const state = await connection.getState();\n  const rpcState = {};\n  return state;\n}'
 p.write_text(original)
 assert v.patch_compiled(p)['matches']==1
 assert 'if (command.trievoWaitForIdle === true) await connection.waitForIdle();' in p.read_text()
 assert v.patch_compiled(p)['status']=='already_applied'
 assert 'return state;' in p.read_text()
