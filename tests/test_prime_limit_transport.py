import pytest
from evolink_bench.baselines.process import _prime_admission_limit_reply

@pytest.mark.parametrize('reason',['max_tool_calls','max_model_calls','episode_timeout'])
def test_exact_pre_prompt_native_limit_becomes_a_bounded_failure_without_work(reason):
    result=_prime_admission_limit_reply('prime-agent','baseline adapter interact failed: Prime Agent Turn budget exhausted: '+reason)
    assert result['raw']['limit_reasons']==[reason]
    assert result['raw']['additional_native_requests']==0
    assert result['text']=='' and result['tool_calls']==[] and result['usage']=={}

@pytest.mark.parametrize('baseline,error',[
    ('codex','baseline adapter interact failed: Prime Agent Turn budget exhausted: max_tool_calls'),
    ('prime-agent','baseline adapter interact failed: HTTP403'),
    ('prime-agent','baseline adapter timed out during interact'),
    ('prime-agent','baseline adapter interact failed: Prime Agent Turn budget exhausted: unknown'),
    ('prime-agent','baseline adapter interact failed: Prime Agent Turn budget exhausted: max_tool_calls; extra error'),
])
def test_other_protocol_policy_and_timeout_errors_cannot_be_converted_to_scores(baseline,error):
    assert _prime_admission_limit_reply(baseline,error) is None
