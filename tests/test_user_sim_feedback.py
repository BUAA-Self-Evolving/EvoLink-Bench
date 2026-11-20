import json

from evolink_bench.user_sim import UserSimulator


def test_plain_action_failure_uses_bounded_feedback_without_private_detail():
    class Client:
        def complete(self, messages, **kwargs):
            content = messages[-1]['content']
            assert 'private-checker-secret' not in content
            data = json.loads(content)
            assert data['schema_version'] == 'l1_bounded_feedback/1.0'
            assert data['public_result_category'] == 'incomplete_task'
            return '{"next_user_message":"Please complete the requested file."}'
    simulator = UserSimulator({'llm_post_failure': {'simulator_prompt': '{bounded_evaluation_feedback}'},
                              'agent_input': {}}, 'task', client=Client())
    assert simulator.next_request(history=[], feedback='Invalid action: private-checker-secret') == 'Please complete the requested file.'


def test_structured_bounded_feedback_keeps_failed_dimensions():
    class Client:
        def complete(self, messages, **kwargs):
            assert json.loads(messages[-1]['content'])['failed_dimensions'] == ['task_success']
            return '{"next_user_message":"Finish the task."}'
    simulator = UserSimulator({'llm_post_failure': {'simulator_prompt': '{bounded_evaluation_feedback}'}},
                              'task', client=Client())
    assert simulator.next_request(history=[], feedback=json.dumps({'failed_dimensions': ['task_success']})) == 'Finish the task.'
