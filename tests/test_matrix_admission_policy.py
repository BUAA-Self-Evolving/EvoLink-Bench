import json
import time

import pytest

from tools import run_new_package_matrix as m


@pytest.mark.parametrize('value', [None, {}, {'pause_admission': 'false'},
    {'pause_admission': False, 'time': time.time() - 1000}])
def test_missing_malformed_or_stale_policy_fails_closed(tmp_path, value):
    path = tmp_path / 'policy.json'
    if value is not None:
        path.write_text(json.dumps(value))
    assert m.admission_policy_state(path)['paused'] is True


def test_optional_policy_preserves_unconfigured_behavior():
    assert m.admission_policy_state(None)['paused'] is False


def test_paid_worker_exit_is_recorded_while_replacement_admission_is_paused(tmp_path, monkeypatch):
    policy = tmp_path / 'policy.json'
    policy.write_text('{"pause_admission": false}')
    rows = [dict(id=str(i), output=str(tmp_path / str(i))) for i in range(2)]
    state = {'jobs': rows}
    launches = []
    observed_pause = []

    class Child:
        def __init__(self, args, **kwargs):
            self.pid = int(args[0]) + 100
            launches.append(args[0])
        def poll(self):
            return 0

    def report(row):
        if not row.get('pid'):
            return None, None
        if row['id'] == '0':
            policy.write_text('{"pause_admission": true}')
        return 'saved-report', {'valid': True}

    def sleep(_):
        if state.get('admission_health', {}).get('paused'):
            assert rows[0]['status'] == 'completed'
            assert launches == ['0']
            observed_pause.append(True)
            policy.write_text('{"pause_admission": false}')

    monkeypatch.setattr(m.subprocess, 'Popen', Child)
    monkeypatch.setattr(m, 'report_for', report)
    monkeypatch.setattr(m, 'latest_checkpoint', lambda row: None)
    monkeypatch.setattr(m, 'command', lambda repo, row, *args: [row['id']])
    monkeypatch.setattr(m, 'process_start_ticks', lambda pid: str(pid))
    monkeypatch.setattr(m, 'matrix', lambda rows: [])
    monkeypatch.setattr(m.time, 'sleep', sleep)
    assert m.run_parallel(tmp_path, rows, rows, tmp_path, state, tmp_path / 'status.json', 1,
                          admission_policy_path=policy) == 0
    assert observed_pause and launches == ['0', '1']
    assert all(row['status'] == 'completed' for row in rows)


@pytest.mark.parametrize('allowed,baseline,paused', [(['hermes'],'hermes',False),
    (['hermes'],'codex',True), ([], 'hermes',True), (None,'hermes',False),
    ('hermes','hermes',True), ([1],'hermes',True)])
def test_cohort_admission_only_starts_selected_baselines(tmp_path, allowed, baseline, paused):
    path=tmp_path/'policy.json'
    path.write_text(json.dumps({'time':time.time(),'pause_admission':False,'allowed_baselines':allowed}))
    assert m.admission_policy_state(path,baseline=baseline)['paused'] is paused


@pytest.mark.parametrize('cap,active,paused', [(0,0,True),(1,0,False),(1,1,True),(2,1,False),(-1,0,True),('2',0,True)])
def test_cohort_cap_keeps_paid_children_but_blocks_excess_admission(tmp_path,cap,active,paused):
    path=tmp_path/'policy.json'
    path.write_text(json.dumps({'pause_admission':False,'baseline_worker_caps':{'hermes':cap}}))
    assert m.admission_policy_state(path,baseline='hermes',active_workers=active)['paused'] is paused
