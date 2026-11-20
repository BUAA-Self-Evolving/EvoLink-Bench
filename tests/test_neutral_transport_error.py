import pytest
from tools.l1_unreturned_recovery import neutral_transport_error

@pytest.mark.parametrize('message',[
 'BaselineProtocolError: baseline adapter interact failed: HTTP 400: upstream Responses stream failed',
 'baseline adapter interact failed: OpenCode request failed: upstream Responses stream ended before completion',
 'baseline adapter interact failed: Prime Agent RPC absolute deadline expired during prompt',
 'baseline adapter interact failed: Error code: 500 - upstream error: do request failed (request id: abc_123)',
])
def test_exact_neutral_interruption_is_classified(message):assert neutral_transport_error(message)

@pytest.mark.parametrize('message',[
 'baseline adapter interact failed: HTTP 403: upstream Responses stream failed',
 'baseline adapter interact failed: HTTP 400: content_filter upstream Responses stream failed',
 'baseline adapter interact failed: 用户已被封禁 upstream Responses stream failed',
 'baseline adapter interact failed: HTTP 400: arbitrary bad request',
 'baseline adapter interact failed: Prime Agent Turn budget exhausted: max_tool_calls',
 'unrelated error upstream Responses stream failed',
])
def test_refusals_unknown_errors_and_valid_budget_limits_are_not_reclassified(message):assert not neutral_transport_error(message)
