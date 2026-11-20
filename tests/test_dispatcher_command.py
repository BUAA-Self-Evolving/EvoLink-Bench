import pytest
from tools.dispatcher_command import set_option

def test_last_argparse_value_cannot_override_the_validated_adoption_width():
    original=['python','driver.py','--concurrency','2','--infrastructure-evidence-map','bound.json','--concurrency','1']
    fixed=set_option(original,'--concurrency','8')
    assert fixed.count('--concurrency')==1 and fixed[-1]=='8'
    assert fixed[fixed.index('--infrastructure-evidence-map')+1]=='bound.json'
    assert original[-1]=='1'

@pytest.mark.parametrize('args',[['--concurrency'],['--concurrency','--root','path']])
def test_malformed_options_fail_before_owner_is_released(args):
    with pytest.raises(ValueError):set_option(args,'--concurrency','8')
