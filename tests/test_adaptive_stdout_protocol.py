import io
import json
import sys
import threading
import os
import subprocess
from pathlib import Path
from baseline.adapters.adaptive_auto_harness import bridge


def test_native_json_noise_and_background_prints_cannot_corrupt_protocol(monkeypatch):
    protocol, noise = io.StringIO(), io.StringIO()
    requests = [dict(id=1, method='initialize', params={}), dict(id=2, method='start_flow', params={}), dict(id=3, method='end_flow', params={})]
    thread = None
    class Fake:
        def __init__(self):
            print('{"native_constructor_log":true}')
        def initialize(self, p):
            print('{"native_initialization_log":true}')
            return {'ok': True}
        def start_flow(self, p):
            nonlocal thread
            thread = threading.Thread(target=lambda: print('{"native_background_log":true}'))
            thread.start();thread.join()
            return {'flow': 'test'}
        def start_turn(self, p):
            return {}
        def interact(self, p):
            raise AssertionError('model interaction forbidden in this test')
        def evolve(self, p):
            raise AssertionError('learning forbidden in this test')
        def end_flow(self, p):
            return {'completed': True}
    monkeypatch.setattr(bridge, 'AdaptiveAutoHarnessBridge', Fake)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''.join(json.dumps(x) + '\n' for x in requests)))
    monkeypatch.setattr(sys, 'stdout', protocol)
    monkeypatch.setattr(sys, 'stderr', noise)
    bridge._serve()
    rows = [json.loads(x) for x in protocol.getvalue().splitlines()]
    assert [x['id'] for x in rows] == [1, 2, 3]
    assert all('result' in x for x in rows)
    assert 'native_constructor_log' in noise.getvalue() and 'native_background_log' in noise.getvalue()
    assert sys.stdout is protocol


def test_error_response_keeps_its_matching_request_id(monkeypatch):
    protocol = io.StringIO()
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{"id":7,"method":"unknown","params":{}}\n'))
    monkeypatch.setattr(sys, 'stdout', protocol)
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    bridge._serve()
    response = json.loads(protocol.getvalue())
    assert response['id'] == 7 and 'error' in response


def test_entrypoint_isolates_fd_writes_original_stdout_and_inherited_children(tmp_path):
    package = tmp_path / 'agent_evolve' / 'protocol'
    package.mkdir(parents=True)
    (package / 'base_agent.py').write_text(
        'import os,sys,subprocess\n'
        'os.write(1,b\'{"fd_diagnostic":true}\\n\')\n'
        'sys.__stdout__.write(\'{"original_stdout":true}\\n\');sys.__stdout__.flush()\n'
        'subprocess.run([sys.executable,"-c",\'import json;print(json.dumps(dict(child_diagnostic=True)))\'],check=True)\n'
        'class BaseAgent: pass\n', encoding='utf-8')
    environment = dict(os.environ, PYTHONPATH=str(tmp_path))
    process = subprocess.run([sys.executable, str(Path(bridge.__file__).resolve())],
        input='{"id":7,"method":"unknown","params":{}}\n'
              '{"id":8,"method":"end_flow","params":{}}\n',
        capture_output=True, text=True, env=environment, timeout=15)
    assert process.returncode == 0, process.stderr
    assert [json.loads(line)['id'] for line in process.stdout.splitlines()] == [7, 8]
    assert all(name in process.stderr for name in
               ('fd_diagnostic', 'original_stdout', 'child_diagnostic'))
