import pytest

from tools.run_new_package_matrix import job_environment
from evolink_bench.provider_profiles import ProviderCredential


def environment(profile=None):
    return job_environment('packycode', (ProviderCredential('PACKYCODE_API_KEY', 'test'),), {},
        {'TRIEVO_PROVIDER_MODEL': 'gpt-6.1-terra', 'TRIEVO_PACKYCODE_GATEWAY_URL': 'http://127.0.0.1:18871/v1'},
        profile_configuration=profile)


def test_explicit_profile_reaches_judge_and_simulator_worker_environment():
    env = environment({'name': 'packycode', 'timeout_seconds': 300, 'max_retries': 2})
    assert env['TRIEVO_API_TIMEOUT_SECONDS'] == '300'
    assert env['TRIEVO_API_MAX_RETRIES'] == '2'
    assert env['TRIEVO_MODEL'] == 'gpt-6.1-terra'
    assert env['TRIEVO_BASE_URL'] == 'http://127.0.0.1:18871/v1'


def test_no_generated_profile_retains_legacy_defaults():
    env = environment()
    assert env['TRIEVO_API_TIMEOUT_SECONDS'] == '150'
    assert env['TRIEVO_API_MAX_RETRIES'] == '4'


@pytest.mark.parametrize('profile', [
    {'name': 'openai'}, {'name': 'packycode', 'timeout_seconds': 0},
    {'name': 'packycode', 'timeout_seconds': 3601}, {'name': 'packycode', 'timeout_seconds': True},
    {'name': 'packycode', 'max_retries': -1}, {'name': 'packycode', 'max_retries': 21},
])
def test_bad_profile_is_rejected_before_worker_dispatch(profile):
    with pytest.raises(ValueError):
        environment(profile)
