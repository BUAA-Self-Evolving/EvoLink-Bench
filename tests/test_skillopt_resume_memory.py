from baseline.adapters.skillopt.bridge import SkillOptBridge


def test_resume_preserves_paid_learned_skill(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    state = tmp_path / 'state'
    workspace.mkdir()
    state.mkdir()
    skill = state / 'skill.md'
    skill.write_text('learned from completed paid turns')
    bridge = SkillOptBridge()
    bridge._initialized = True
    monkeypatch.setattr(bridge, '_load_config', lambda: {})
    monkeypatch.setattr(bridge, '_configure_models', lambda: None)
    monkeypatch.setattr(bridge, '_token_summary', lambda: {})
    monkeypatch.setattr(bridge, '_initial_skill', lambda: 'fresh default')
    bridge.start_flow({'workspace': str(workspace), 'state_dir': str(state), 'flow_id': 'resume'})
    assert skill.read_text() == 'learned from completed paid turns'


def test_fresh_flow_still_initializes_skill(tmp_path, monkeypatch):
    bridge = SkillOptBridge()
    bridge._initialized = True
    monkeypatch.setattr(bridge, '_load_config', lambda: {})
    monkeypatch.setattr(bridge, '_configure_models', lambda: None)
    monkeypatch.setattr(bridge, '_token_summary', lambda: {})
    monkeypatch.setattr(bridge, '_initial_skill', lambda: 'fresh default')
    bridge.start_flow({'workspace': str(tmp_path), 'state_dir': str(tmp_path / 'state'), 'flow_id': 'fresh'})
    assert bridge.skill_file.read_text() == 'fresh default'
