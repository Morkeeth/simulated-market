"""Typed reading tasks and a strict structured-output shape. No provider calls.

The compiler is a bounded English/French fallback, not an LLM or general language
understanding. Unknown task verbs cannot earn completion without clarification.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

VERSION = 1
MOVE_NAMES = ('went_somewhere', 'came_back', 'wrote')
TASK_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['task', 'intent', 'required_moves'],
    'properties': {
        'task': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'intent': {'type': 'string', 'enum': ['read', 'write', 'unknown']},
        'required_moves': {'type': 'array', 'uniqueItems': True,
                           'items': {'type': 'string', 'enum': list(MOVE_NAMES)}},
    },
}
WRITE_VERB = r'post|upload|save|create|make|add|share|publish|submit|send|buy|order|book|sign.?up|register|join|write|record|import|bring in|install|connect|invite|vote|pay|publier|poster|enregistrer|créer|creer|ajouter|partager|envoyer|acheter|réserver|reserver|inscrire|importer|téléverser|televerser'
READ_VERB = r'read|find|see|learn|understand|explain|inspect|open|view|check|work out|before trusting|lire|trouver|voir|apprendre|comprendre|consulter|ouvrir|vérifier|verifier'
WRITE_START = re.compile(r'^\s*(?:to\s+)?(?:' + WRITE_VERB + r')\b', re.I)
READ_START = re.compile(r'^\s*(?:' + READ_VERB + r')\b', re.I)
RETURN = re.compile(r'\b(?:return|returns|revisit|come back|comes back|go back|get back|back to|revenir|retourner|revenez|retournez)\b', re.I)
SEQUENCE = re.compile(r'\b(?:and then|then|after that|afterwards|puis|ensuite)\b', re.I)
CLAUSE = re.compile(r'\b(?:and then|then|and|puis|ensuite|et)\b', re.I)
ABOUT = re.compile(r'\b(?:how to|comment|(?:guide|tutorial|instructions)\s+(?:on|about|to|for))\b', re.I)
PREFIX = re.compile(r'^Do what people come to this app for:\s*', re.I)

@dataclass(frozen=True)
class TaskContract:
    task: str
    intent: str
    required_moves: tuple[str, ...]

    def payload(self):
        return {'task': self.task, 'intent': self.intent,
                'required_moves': list(self.required_moves)}


def validate(payload) -> TaskContract:
    """Fail closed on bad or contradictory data before an enforcement rail runs."""
    if not isinstance(payload, dict) or set(payload) != {'task', 'intent', 'required_moves'}:
        raise ValueError('A task contract needs exactly task, intent and required_moves.')
    task, intent, moves = (payload[k] for k in ('task', 'intent', 'required_moves'))
    if not isinstance(task, str) or not task.strip() or len(task) > 500:
        raise ValueError('A task must be a short nonempty string.')
    if intent not in ('read', 'write', 'unknown') or not isinstance(intent, str):
        raise ValueError('Choose read, write or unknown intent.')
    if not isinstance(moves, list) or any(not isinstance(m, str) or m not in MOVE_NAMES for m in moves):
        raise ValueError('Unknown task move.')
    if len(moves) != len(set(moves)):
        raise ValueError('Repeated task move.')
    if intent == 'write' and moves != ['wrote']:
        raise ValueError('Write tasks must retain the write requirement.')
    if intent != 'write' and 'wrote' in moves:
        raise ValueError('Read/unknown task cannot contain a write move.')
    if 'came_back' in moves and moves != ['went_somewhere', 'came_back']:
        raise ValueError('A return must follow leaving the first screen.')
    return TaskContract(task.strip(), intent, tuple(moves))


def compile_task(task: str) -> TaskContract:
    text = PREFIX.sub('', task or '').strip().rstrip('.')
    if not text:
        return validate({'task': '(task missing)', 'intent': 'unknown', 'required_moves': []})
    # Content being read is not an instruction to act. Preserve later action
    # clauses so "read how to post, then upload" still requires a write.
    actions = []
    for part in CLAUSE.split(text):
        part = part.strip(' ,;.')
        if READ_START.search(part):
            part = ABOUT.split(part, maxsplit=1)[0]
        actions.append(part)
    writes = any(WRITE_START.search(part) for part in actions)
    intent = 'write' if writes else 'read' if READ_START.search(text) or RETURN.search(text) else 'unknown'
    # Read task descriptions such as "Read how to return" do not themselves
    # require navigation back; only the surviving action clauses do.
    returns = any(RETURN.search(part) for part in actions)
    moves = ['wrote'] if writes else ['went_somewhere', 'came_back'] if returns else ['went_somewhere'] if SEQUENCE.search(text) else []
    return validate({'task': text, 'intent': intent, 'required_moves': moves})


def structured_request(task: str) -> dict:
    """Build a Nebius-compatible proposed request shape; never sends it.

    A future caller must check exact endpoint support and independently validate
    task semantics. Valid JSON is not evidence a task interpretation is correct.
    """
    # The observed provider grammar rejects uniqueItems. Keep that constraint
    # in local validation, rather than weakening the accepted task contract.
    import copy
    transport_schema = copy.deepcopy(TASK_SCHEMA)
    transport_schema['properties']['required_moves'].pop('uniqueItems')
    return {'messages': [{'role': 'system', 'content': 'Describe the intended task, not actions mentioned in a tutorial. Return task, intent and required_moves. Copy the ENTIRE user message verbatim into task; do not shorten or rewrite it. Navigation away is went_somewhere; returning requires went_somewhere then came_back. Reading about posting is read; actual posting is write with wrote. Keep every ordered step. Do not repeat any move.'},
                         {'role': 'user', 'content': task}],
            'response_format': {'type': 'json_schema', 'json_schema':
                                {'name': 'reading_task', 'strict': True, 'schema': transport_schema}}}


def compile_runtime(task, client):
    """One explicit paid call; caller owns authorization and reservation.

    Never silently falls back after a failed provider response. Schema validity
    does not prove semantic validity; preserve the response for review.
    """
    import json
    request = structured_request(task)
    reply = client.chat(request['messages'], max_tokens=512,
                        chat_template_kwargs={'enable_thinking': False},
                        response_format=request['response_format'])
    if reply.finish_reason != 'stop':
        raise ValueError('Task contract response was not complete.')
    contract = validate(json.loads(reply.text))
    if contract.task != task.strip():
        raise ValueError('The model changed the task. No task contract was accepted.')
    return contract, reply
