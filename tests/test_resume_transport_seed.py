import zipfile
from types import SimpleNamespace

import pytest

from evolink_bench.baselines.process import ProcessBaselineRuntime, BaselineProtocolError
from evolink_bench.model import TokenBudget


@pytest.mark.parametrize('override', [False, True])
def test_resume_keeps_learning_and_only_opted_in_guarded_transport_changes(tmp_path, override):
    seed = tmp_path / 'seed'
    seed.mkdir()
    (seed / 'config.yaml').write_text('base_url: new-endpoint')
    archive = tmp_path / 'old-state.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('config.yaml', 'base_url: old-endpoint')
        bundle.writestr('memories/MEMORY.md', 'completed paid learning')
        bundle.writestr('.trievo_semantic_state.json', '{"fact": "preserved"}')
    before = archive.read_bytes()
    state = dict(seed_from=str(seed), seed_files=['config.yaml'], guard_paths=['config.yaml'])
    if override:
        state['resume_transport_seed_files'] = ['config.yaml']
    runtime = ProcessBaselineRuntime(SimpleNamespace(baseline_id='hermes', state=state, options={}),
                                     budget=TokenBudget(limit=10), repo_root=tmp_path,
                                     resume_state_archive=archive)
    runtime._state_dir = tmp_path / 'state'
    runtime._state_dir.mkdir()
    runtime._seed_state()
    assert (runtime._state_dir / 'config.yaml').read_text() == ('base_url: new-endpoint' if override else 'base_url: old-endpoint')
    assert (runtime._state_dir / 'memories/MEMORY.md').read_text() == 'completed paid learning'
    assert runtime._semantic_state == {'fact': 'preserved'}
    assert archive.read_bytes() == before


def test_transport_override_cannot_replace_learning_file(tmp_path):
    archive = tmp_path / 'state.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('memories/MEMORY.md', 'paid learning')
    state = dict(seed_from=str(tmp_path), seed_files=[], guard_paths=[],
                 resume_transport_seed_files=['memories/MEMORY.md'])
    runtime = ProcessBaselineRuntime(SimpleNamespace(baseline_id='hermes', state=state, options={}),
                                     budget=TokenBudget(limit=10), repo_root=tmp_path,
                                     resume_state_archive=archive)
    runtime._state_dir = tmp_path / 'out'
    runtime._state_dir.mkdir()
    with pytest.raises(BaselineProtocolError, match='guarded config.yaml'):
        runtime._seed_state()
