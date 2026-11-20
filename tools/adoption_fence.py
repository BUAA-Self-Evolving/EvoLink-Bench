"""Fence a dispatcher handoff against fork-before-publication races (Linux)."""
from pathlib import Path
import os,signal,time
from tools.run_new_package_matrix import process_start_ticks

def fields(pid,proc=Path('/proc')):
 return (proc/str(pid)/'stat').read_text().rsplit(')',1)[1].split()

def quiesce(pid,birth,timeout=2):
 if process_start_ticks(pid)!=str(birth):raise ValueError('dispatcher birth changed; no signal sent')
 os.kill(pid,signal.SIGSTOP);deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  if process_start_ticks(pid)!=str(birth):raise ValueError('dispatcher exited while stopping')
  tasks=list((Path('/proc')/str(pid)/'task').iterdir())
  if tasks and all(fields(t.name)[0] in ('T','t') for t in tasks):return
  time.sleep(.01)
 raise TimeoutError('dispatcher did not quiesce')

def assert_published_children(pid,rows,proc=Path('/proc')):
 if fields(pid,proc)[0] not in ('T','t'):raise ValueError('dispatcher is not quiescent')
 receipts={int(r['pid']):str(r['process_start_ticks']) for r in rows if r.get('status')=='running' and r.get('pid') and r.get('process_start_ticks') is not None}
 children=set()
 for task in (proc/str(pid)/'task').iterdir():
  children.update(int(x) for x in (task/'children').read_text().split())
 for child in children:
  try:birth=fields(child,proc)[19]  # Includes zombies: an unreported exit is still a launch boundary.
  except (OSError,IndexError):raise ValueError('unpublished child exit boundary; original owner must reap')
  if receipts.get(child)!=birth:raise ValueError('unpublished or unverified child; preserve original dispatcher')
 return sorted(children)


def assert_terminal_owner_clear(pid: int, matrix: Path, state: dict, proc: Path = Path('/proc')) -> dict:
    """Require a terminal empty owner and no unpublished root/job processes; caller holds the adoption lock."""
    if type(pid) is not int or pid <= 0 or state.get('status') not in ('completed', 'completed_with_errors'):
        raise ValueError('full owner is not demonstrably terminal')
    if state.get('adopted_rows') or any(row.get('status') == 'running' for row in state.get('jobs', [])):
        raise ValueError('terminal owner still has paid or unpublished receipts')
    parent = proc / str(pid)
    terminal_state = None
    if parent.exists():
        terminal_state = fields(pid, proc)[0]
        if terminal_state != 'Z' or (parent / 'cmdline').read_bytes().strip(b'\0'):
            raise ValueError('owner process remains live or identity is ambiguous')
        for task in (parent / 'task').iterdir():
            if (task / 'children').read_text().strip():
                raise ValueError('terminal owner retains unreconciled children')
    root = str(matrix).encode()
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        if any(arg == root or arg.startswith(root + b'/') for arg in args):
            raise ValueError('unpublished full owner or native job still exists')
    return {'old_pid': pid, 'terminal_state': terminal_state, 'published_status': state['status'],
            'root_and_job_process_inventory_empty': True}
