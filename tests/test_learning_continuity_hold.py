import json
import pytest
from tools import run_new_package_matrix as m

def fixture(tmp_path):
 row=dict(level='l2',id='l2/evolving/skillopt/s02',agent='skillopt',flow_id='stream',condition='evolving',turns=['t1','t2'],output=str(tmp_path))
 turns=[dict(turn_id=t,condition='evolving',turn_score=0,passed=False,evaluation_status='failed',final_category='fail') for t in row['turns']]
 report=dict(stream_id='stream',condition='evolving',baseline='skillopt',turns=turns)
 marker=tmp_path/'_learning_continuity_hold.json';marker.write_text(json.dumps({'status':'unresolved','valid_prefix_turns':1}))
 return row,report,marker

def test_valid_prefix_survives_but_corrupted_suffix_cannot_aggregate(tmp_path):
 row,report,_=fixture(tmp_path)
 assert m._report_matches_row({**row,'turns':['t1']},{**report,'turns':report['turns'][:1]})
 assert not m._report_matches_row(row,report)

def test_unresolved_hold_blocks_automatic_checkpoint_rollback(tmp_path):
 row,_,_=fixture(tmp_path)
 with pytest.raises(ValueError,match='learning continuity hold'):m.latest_checkpoint(row)

def test_unresolved_hold_does_not_consume_interrupted_retry_authorization(tmp_path):
 row,_,_=fixture(tmp_path);auth=tmp_path/'ledger.json';auth.write_text('{"status":"authorized_not_consumed"}')
 with pytest.raises(ValueError,match='learning continuity hold'):m.prepare_interrupted_retry(row,'failed-run',auth)
 assert json.loads(auth.read_text())['status']=='authorized_not_consumed'

def test_corrupt_hold_fails_closed(tmp_path):
 row,report,marker=fixture(tmp_path);marker.write_text('{invalid')
 assert not m._report_matches_row(row,report)
 with pytest.raises(ValueError):m.latest_checkpoint(row)
