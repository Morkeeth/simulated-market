"""Retained navigation-only false approval and successful siblings."""
import pytest
from sim import app_swarm

@pytest.mark.parametrize('task,quote,content,status,expected', [
    ('See what Lumen Notes costs', 'Pricing', 'Lumen Notes keeps your notes in one place.', 200, False),
    ('Find the subscription price', 'View prices', 'The calculator explains how our subscription works.', 200, False),
    ('See the price of Atlas', '$19 per month', '404 Pricing $19 per month. This page does not exist.', 404, False),
    ('See what Lumen Notes costs', 'Starter plan is $19 per month.', 'Starter plan is $19 per month.', 200, True),
    ('Find the subscription price', 'Our subscription is free for everyone.', 'Our subscription is free for everyone.', 200, True),
    ('Read the getting started guide', 'Start by opening a collection, then choose one note to read.', 'Start by opening a collection, then choose one note to read.', 200, True),
])
def test_content_guard(task, quote, content, status, expected):
    state = app_swarm.completion(task, True, [{'url': 'https://example.invalid/', 'action': 'look'}], evidence=quote, content=content, http_status=status)
    assert (state['state'] == 'job_completed') == expected
