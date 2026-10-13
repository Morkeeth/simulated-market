"""CPU contract/rail checks. No NeMo SDK, model, browser or provider is invoked."""
import pytest
from sim import app_swarm, task_contract, task_rail

DIRECT = [{'url': 'https://fixture.invalid/', 'action': 'open'}]
AWAY = DIRECT + [{'url': 'https://fixture.invalid/story', 'action': 'click'}]
FULL = AWAY + [{'url': 'https://fixture.invalid/', 'action': 'back'}]

@pytest.mark.parametrize('job,trail,state', [
    ('Lire un article puis revenir à la collection', DIRECT, 'screen_confirmed'),
    ('Read an essay, then revisit the collection', AWAY, 'screen_confirmed'),
    ('Read a story and return to the collection', FULL, 'job_completed'),
])
def test_task_steps_are_enforced_separately_from_screen_confirmation(job, trail, state):
    assert app_swarm.completion(job, True, trail)['state'] == state
    assert app_swarm.completion(job, False, FULL)['state'] == 'claimed'


def test_tutorial_content_does_not_become_the_intended_act():
    task = 'Read the tutorial on how to post a run'
    assert not app_swarm.needs_write(task)
    assert not app_swarm.personas_for(task)[0].get('start_only')
    assert app_swarm.needs_write('Read how to post, then upload a run')
    assert app_swarm.required_moves('Post a run') == ['wrote']
    assert app_swarm.completion('Post a run', True, FULL)['state'] == 'screen_confirmed'


@pytest.mark.parametrize('payload', [
    {}, {'task': 'Read', 'intent': 'read', 'required_moves': [], 'done': True},
    {'task': 'Post a run', 'intent': 'write', 'required_moves': []},
    {'task': 'Read', 'intent': 'read', 'required_moves': ['wrote']},
    {'task': 'Return', 'intent': 'read', 'required_moves': ['came_back']},
    {'task': 'Read', 'intent': 'read', 'required_moves': ['went_somewhere', 'went_somewhere']},
    {'task': 'Read', 'intent': 'read', 'required_moves': ['invented']},
])
def test_malformed_contracts_are_rejected_before_enforcement(payload):
    with pytest.raises(ValueError):
        task_contract.validate(payload)


def test_failed_navigation_and_scroll_do_not_prove_a_return():
    task = task_contract.compile_task('Read a story and return')
    assert not task_rail.enforce(task, AWAY + [{'url': 'https://fixture.invalid/', 'status': 'not_allowed'}]).allowed
    assert not task_rail.enforce(task, DIRECT + [{'url': 'https://fixture.invalid/#part'}]).allowed
    assert task_rail.enforce(task, FULL).allowed


def test_unknown_task_needs_clarification_and_prompts_keep_the_contract():
    assert app_swarm.completion('Blorb the widget', True, FULL) == {'state': 'screen_confirmed', 'missing': ['task_contract']}
    messages = app_swarm.confirm_messages({'goal': 'Read and return'}, 'Screen text', AWAY)
    assert 'required_moves' in messages[0]['content']
    assert messages[-1]['content'] == 'Screen text'


def test_structured_request_is_only_a_payload_and_has_no_completion_claim():
    request = task_contract.structured_request('Read and return')
    assert request['response_format']['type'] == 'json_schema'
    schema = request['response_format']['json_schema']['schema']
    assert schema['additionalProperties'] is False
    assert schema['properties']['intent']['enum'] == ['read', 'write', 'unknown']
    assert 'done' not in schema['properties']
