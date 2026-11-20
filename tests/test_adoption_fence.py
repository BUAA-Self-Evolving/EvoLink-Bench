from pathlib import PurePosixPath
from pathlib import Path
import json,os,signal,subprocess,sys,time
import pytest
from tools import adoption_fence as f
from tools.run_new_package_matrix import process_start_ticks

def stat(root,pid,state,birth):
 p=root/str(pid);p.mkdir(parents=True,exist_ok=True);parts=[state]+['0']*21;parts[19]=str(birth);(p/'stat').write_text(f'{pid} (test) '+' '.join(parts))
@pytest.mark.parametrize('variant',['known','zombie','unknown','birth_changed','not_running','parent_active'])
def test_only_published_original_children_can_survive_handoff(tmp_path,variant):
 stat(tmp_path,100,'R' if variant=='parent_active' else 'T',1000);stat(tmp_path,200,'Z' if variant=='zombie' else 'S',2000)
 task=tmp_path/'100/task/100';task.mkdir(parents=True);(task/'children').write_text('200')
 rows=[] if variant=='unknown' else [{'pid':200,'process_start_ticks':'wrong' if variant=='birth_changed' else '2000','status':'pending' if variant=='not_running' else 'running'}]
 if variant in ('known','zombie'):assert f.assert_published_children(100,rows,tmp_path)==[200]
 else:
  with pytest.raises(ValueError):f.assert_published_children(100,rows,tmp_path)

@pytest.mark.skipif(sys.platform!='linux',reason='Linux dispatcher ownership fence')
def test_wrong_birth_never_stops_process():
 with pytest.raises(ValueError,match='no signal sent'):f.quiesce(os.getpid(),'wrong')

@pytest.mark.skipif(sys.platform!='linux',reason='Linux dispatcher ownership fence')
def test_real_fork_before_receipt_publication_is_deferred_without_losing_child(tmp_path):
 script="""from pathlib import Path
import subprocess,sys,time
p=Path(sys.argv[1]);child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)']);(p/'child').write_text(str(child.pid))
while not (p/'release').exists():time.sleep(.01)
(p/'published').write_text(str(child.pid))
time.sleep(15)
"""
 parent=subprocess.Popen([sys.executable,'-u','-c',script,str(tmp_path)]);pb=process_start_ticks(parent.pid);child=None;cb=None
 def wait(path):
  until=time.monotonic()+3
  while time.monotonic()<until:
   if path.exists() and path.read_text():return path.read_text()
   time.sleep(.01)
  raise AssertionError('test fixture did not publish')
 try:
  child=int(wait(tmp_path/'child'));cb=process_start_ticks(child);f.quiesce(parent.pid,pb)
  with pytest.raises(ValueError,match='unpublished'):f.assert_published_children(parent.pid,[])
  os.kill(parent.pid,signal.SIGCONT);(tmp_path/'release').write_text('go');wait(tmp_path/'published');f.quiesce(parent.pid,pb)
  assert f.assert_published_children(parent.pid,[{'pid':child,'process_start_ticks':cb,'status':'running'}])==[child]
 finally:
  if process_start_ticks(parent.pid)==pb:os.kill(parent.pid,signal.SIGCONT);parent.terminate()
  parent.wait(timeout=3)
  if child and process_start_ticks(child)==cb:os.kill(child,signal.SIGTERM)

@pytest.mark.parametrize('variant',['clear_zombie','clear_absent','live_owner','running_row','adopted_row','unfinished_owner','unpublished_root','unpublished_job','unreconciled_child'])
def test_terminal_owner_handoff_never_discards_hidden_work(tmp_path,variant):
 matrix=PurePosixPath('/experiment/matrix');state={'status':'completed_with_errors','jobs':[]}
 if variant!='clear_absent':
  stat(tmp_path,100,'S' if variant=='live_owner' else 'Z',1000)
  (tmp_path/'100/cmdline').write_bytes(b'')
  task=tmp_path/'100/task/100';task.mkdir(parents=True);(task/'children').write_text('200' if variant=='unreconciled_child' else '')
 if variant=='running_row':state['jobs']=[{'status':'running','pid':200,'process_start_ticks':'2000'}]
 if variant=='adopted_row':state['adopted_rows']=[{'pid':200}]
 if variant=='unfinished_owner':state['status']='running_with_errors'
 if variant in ('unpublished_root','unpublished_job'):
  stat(tmp_path,200,'S',2000);arg=str(matrix) if variant=='unpublished_root' else str(matrix/'l2/reset/x/s01')
  (tmp_path/'200/cmdline').write_bytes(b'python\0-m\0worker\0'+arg.encode()+b'\0')
 if variant.startswith('clear_'):
  assert f.assert_terminal_owner_clear(100,matrix,state,tmp_path)['root_and_job_process_inventory_empty']
 else:
  with pytest.raises(ValueError):f.assert_terminal_owner_clear(100,matrix,state,tmp_path)
