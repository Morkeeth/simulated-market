"""Mini-swe-agent shell participant for a controller-owned local tool gateway."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from sim.agent_protocol import SYSTEM, OBSERVATION, SUBMIT
from sim.standins.docker_sandbox import _docker

MAX_TOKENS=1024
INSTANCE='''A user asked you to use a command-line tool for this task:

{{task}}

The registered tool is available as the command `tool`. It routes arguments to the real frozen tool version. Use `tool --help` to inspect its interface. All task inputs and tool source are in /work and read-only. The supplied documentation is /work/DISCOVERY.md. You may read files, write and run helper code in your writable working directory /agent, inspect outputs and recover from mistakes. Use the registered `tool` command for task invocations so the controller can independently check actual tool output. Calling source files directly is not a registered invocation. Do not change task inputs or tool source. No network is available.
'''


def main():
    ap=argparse.ArgumentParser()
    for name in ('fork','base-url','model','task-file','out'):ap.add_argument('--'+name,required=True)
    ap.add_argument('--seed',type=int,required=True);ap.add_argument('--budget',type=int,required=True)
    a=ap.parse_args()
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.exceptions import FormatError, Submitted
    from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel
    steps=[]
    class Environment:
        config=None
        def execute(self,action,cwd=''):
            command=action.get('command','')
            import subprocess
            try:
                p=_docker('exec','--user','1000:1000','-w','/agent',a.fork,'bash','-c',command,check=False,timeout=45)
                output=(p.stdout+p.stderr).decode(errors='replace')[:20000];code=p.returncode
            except subprocess.TimeoutExpired:code,output=124,'Agent shell command timed out.'
            step={'command':command,'returncode':code,'output':output};steps.append(step)
            with Path(a.out).with_suffix('.trace.jsonl').open('a') as stream:stream.write(json.dumps(step)+'\n')
            if output.strip().splitlines() and output.strip().splitlines()[0]==SUBMIT and code==0:
                raise Submitted({'role':'exit','content':'','extra':{'exit_status':'Submitted','submission':''}})
            return {'returncode':code,'output':output,'exception_info':''}
        def get_template_vars(self,**kwargs):return {}
        def serialize(self):return {}
    class Agent(DefaultAgent):
        def step(self):
            try:return super().step()
            except FormatError as e:
                steps.append({'format_error':str(e)[:1000]});raise
    requests=[]
    class Model(LitellmTextbasedModel):
        abort_exceptions=[Exception]
        def _query(self,messages,**kwargs):
            row={'attempt':len(requests)+1};requests.append(row)
            try:
                response=super()._query(messages,**kwargs)
                row['usage']=response.usage.model_dump() if response.usage else {}
                return response
            except Exception as e:
                row['error']=type(e).__name__;raise
    model=Model(model_name='openai/'+a.model,cost_tracking='ignore_errors',observation_template=OBSERVATION,
                              model_kwargs={'api_base':a.base_url,'api_key':'local','temperature':0.,'seed':a.seed,'max_tokens':MAX_TOKENS,'drop_params':True})
    agent=Agent(model,Environment(),system_template=SYSTEM,instance_template=INSTANCE,step_limit=a.budget,cost_limit=0.,max_consecutive_format_errors=3)
    result={'exit_status':'operational_error','steps':steps}
    try:
        info=agent.run(Path(a.task_file).read_text())
        result['exit_status']=info.get('exit_status','unknown')
    except Exception as e:result['error']=type(e).__name__+': '+str(e)[:400]
    finally:
        result['model_calls']=len(requests)
        result['requests']=requests
        result['messages']=agent.messages
        result['usage']={}
        for row in requests:
            for key,value in row.get('usage',{}).items():
                if isinstance(value,(int,float)):result['usage'][key]=result['usage'].get(key,0)+value
        Path(a.out).write_text(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
