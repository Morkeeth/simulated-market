"""A downloadable project draft, never an API post or funded human test."""
from urllib.parse import urlsplit
from sim.task_contract import compile_task

QUESTIONS = [
    {'id':'did_task_work','text':'Did this task work?'},
    {'id':'what_was_unclear','text':'What was unclear?'},
    {'id':'would_you_pay','text':'Would you pay?'},
]

def project_draft(url, task):
    target=urlsplit(url)
    if target.scheme not in ('http','https') or not target.hostname or target.username or target.password:
        raise ValueError('A web address without embedded credentials is required.')
    return {
        'schema':'first-users/favour-project-draft/1', 'status':'DRAFT_NOT_POSTED',
        'project':{'url':url,'title':'First Users task check','task':compile_task(task).payload(),
                   'question_ids':[q['id'] for q in QUESTIONS],'questions':QUESTIONS},
        'reward_plan':{'reviews':10,'mode':'builder_escrow','amount_per_review_usdc':0.5,
                       'maximum_usdc':5,'funding_status':'UNFUNDED','requires_builder_signature':True},
        'test_deck':[
            {'card':1,'kind':'first_impression','choices':4},
            {'card':2,'kind':'task_result','choices':['yes','partly','no']},
            {'card':3,'kind':'builder_questions','question_ids':[q['id'] for q in QUESTIONS],'scale':[1,2,3,4,5]},
            {'card':4,'kind':'screenshot','required':True},
            {'card':5,'kind':'return_intent','choices':['yes','no'],'optional_sentence_max_chars':140},
        ],
        'verification':{'verified_humans_required':True,'screenshot_required':True,'accepted_reviews':0},
        'public_url_needed':target.hostname in ('localhost','127.0.0.1','::1'),
        'compatibility':'Proposed URL/questions/reward-plan shape and five-card deck. Question IDs are this export format; existing FAVOUR API acceptance is unverified. A human must post and sign funding. No testers invited or paid.',
    }
