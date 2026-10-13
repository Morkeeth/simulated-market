"""Real mini-swe-agent harness, Token Factory chat, and the session's Nebius fork.

No shell executes on the host and no local model fallback is reachable here.
"""
from importlib.metadata import version, PackageNotFoundError
import os
import tempfile
from sim.agent_protocol import (HARNESS, HARNESS_VERSION, STEP_LIMIT, MAX_TOKENS,
    OUTPUT_CAP, SUBMIT, SYSTEM, INSTANCE, OBSERVATION, task_text, runs_marked_code)


def require_harness():
    try:
        if version(HARNESS) == HARNESS_VERSION:
            return
    except PackageNotFoundError:
        pass
    raise RuntimeError('Install requirements-sponsor.txt in the workspace Python environment; mini-swe-agent 2.4.6 is required.')


class CodingAgents:
    label = 'RUNTIME'

    def __init__(self, *, k, client, seed, step_limit=STEP_LIMIT):
        require_harness()
        self.k, self.client, self.seed, self.step_limit = k, client, seed, step_limit
        self.backend_name = f'{HARNESS} {HARNESS_VERSION} with token-factory {client.model}'
        self.info = {'k': k, 'harness': HARNESS, 'harness_version': HARNESS_VERSION,
                     'model': client.model, 'runtime': 'token-factory', 'temperature': 0.0,
                     'seed': seed, 'step_limit': step_limit, 'max_tokens': MAX_TOKENS, 'output_cap': OUTPUT_CAP}

    def act(self, session, section):
        # mini-swe-agent imports a global dotenv file by default. Keep this run's
        # configuration empty and private; only the explicit ChatClient has a key.
        with tempfile.TemporaryDirectory(prefix='sim-sponsor-agent-') as directory:
            names = {'MSWEA_GLOBAL_CONFIG_DIR': directory, 'MSWEA_SILENT_STARTUP': '1'}
            before = {key: os.environ.get(key) for key in names}
            os.environ.update(names)
            try:
                return self._act(session, section)
            finally:
                for key, value in before.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value

    def _act(self, session, section):
        from minisweagent.agents.default import DefaultAgent
        from minisweagent.exceptions import FormatError, Submitted
        from minisweagent.models.utils.actions_text import parse_regex_actions, format_observation_messages
        client, seed = self.client, self.seed

        class Model:
            def get_template_vars(self): return {}
            def serialize(self): return {}
            def format_message(self, **kwargs): return kwargs
            def query(self, messages):
                reply = client.chat([{'role': m['role'], 'content': m['content']} for m in messages],
                                    seed=seed, temperature=0.0, max_tokens=MAX_TOKENS)
                try:
                    actions = parse_regex_actions(reply.text, action_regex=r'```mswea_bash_command\s*\n(.*?)\n```',
                        format_error_template='Provide exactly one bash action; found {{actions|length}}.')
                except FormatError:
                    session.note('skip', 'agent reply had no single command')
                    raise
                return {'role': 'assistant', 'content': reply.text, 'extra': {'actions': actions}}
            def format_observation_messages(self, message, outputs, template_vars=None):
                return format_observation_messages(outputs, observation_template=OBSERVATION, template_vars=template_vars)

        class Environment:
            def get_template_vars(self): return {}
            def serialize(self): return {}
            def execute(self, action):
                command = action['command']
                code, out = session.fork.exec(['bash', '-c', command])
                def read_file(path):
                    c, text = session.fork.exec(['cat', path]); return text if c == 0 else None
                marked = (False if 'scenario' in session.target.meta else
                          runs_marked_code(command, read_file, session.target.meta['app_marker']))
                session.record('run', command, code, out, marker_run=marked)
                lines = out.lstrip().splitlines()
                if code == 0 and lines and lines[0].strip() == SUBMIT:
                    raise Submitted({'role': 'exit', 'content': '', 'extra': {'exit_status': 'Submitted', 'submission': ''}})
                return {'returncode': code, 'output': out, 'exception_info': ''}

        agent = DefaultAgent(Model(), Environment(), system_template=SYSTEM, instance_template=INSTANCE,
                             step_limit=self.step_limit, cost_limit=0.0, max_consecutive_format_errors=3)
        # Cost is unknown and tracked by provider usage receipts, not an invented USD estimate.
        status = agent.run(task_text(session.target.meta, section)).get('exit_status', 'unknown')
        session.note('done' if status == 'Submitted' else 'give_up', 'agent stopped: ' + status)
        return status
