"""Container-only persistent stdio MCP transport; no model or host credentials."""
import importlib.util
import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
import sys
import time
import http.server


def session(plan, receipt=Path('/receipt')):
    receipt.mkdir(exist_ok=True)
    state={'status':'running','calls':[],'model_calls':0,'server_pid':None}
    wire=(receipt/'wire.jsonl').open('w',buffering=1)
    def save(): (receipt/'session.json').write_text(json.dumps(state,indent=2)+'\n')
    proc=None;server=None;stderr=None;pending=b'';request_id=0
    def send(value):
        raw=(json.dumps(value)+'\n').encode();wire.write(json.dumps({'direction':'client-to-server','raw':raw.decode()})+'\n')
        proc.stdin.write(raw);proc.stdin.flush()
    def request(method,params):
        nonlocal request_id,pending
        request_id+=1;send({'jsonrpc':'2.0','id':request_id,'method':method,'params':params})
        deadline=time.monotonic()+plan['timeout_seconds']
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout,selectors.EVENT_READ)
            while True:
                while b'\n' not in pending:
                    remaining=deadline-time.monotonic()
                    if remaining<=0 or not selector.select(remaining):raise TimeoutError('MCP response timed out')
                    chunk=os.read(proc.stdout.fileno(),65536)
                    if not chunk:raise EOFError('MCP server closed stdout')
                    pending+=chunk
                    if len(pending)>2000000:raise ValueError('MCP response exceeds 2 MB line limit')
                line,pending=pending.split(b'\n',1)
                wire.write(json.dumps({'direction':'server-to-client','raw':line.decode()+'\n'})+'\n')
                response=json.loads(line)
                if response.get('id')!=request_id:continue
                if 'error' in response:raise ValueError('MCP error: '+json.dumps(response['error']))
                if not isinstance(response.get('result'),dict):raise ValueError('MCP result must be an object')
                return response['result']
    save()
    try:
        spec=importlib.util.spec_from_file_location('fixture','/frozen/fixture.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',80),fixture.Fixture)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        stderr=(receipt/'server.stderr').open('wb')
        proc=subprocess.Popen(['/frozen/server',*plan['argv']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,
            env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','GITHUB_PERSONAL_ACCESS_TOKEN':'LOCAL-SYNTHETIC-DUMMY-NOT-A-CREDENTIAL'})
        state['server_pid']=proc.pid;save()
        state['initialize']=request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'simulated-market-local-session','version':'1'}});save()
        send({'jsonrpc':'2.0','method':'notifications/initialized','params':{}})
        state['tools']=request('tools/list',{});save()
        advertised={row['name'] for row in state['tools']['tools']}
        def calls():
            if not plan.get('participant'):
                yield from plan['calls'];return
            print(json.dumps({'ready':True,'tools':state['tools']}),flush=True)
            for _ in range(plan['max_calls']):
                raw=sys.stdin.readline()
                if not raw:raise EOFError('Controller closed before session stop')
                value=json.loads(raw)
                if value=={'stop':True}:return
                if not isinstance(value,dict) or set(value)!={'name','arguments'}:raise ValueError('Invalid gateway call')
                yield value
            raise ValueError('Participant MCP budget exhausted')
        for call in calls():
            row={'request':call,'status':'started','server_pid':proc.pid};state['calls'].append(row);save()
            if call['name'] not in advertised:raise ValueError('Tool was not advertised: '+call['name'])
            row['result']=request('tools/call',call);row['status']='tool_error' if row['result'].get('isError') else 'complete';save()
            if plan.get('participant'):print(json.dumps({'result':row['result']}),flush=True)
            elif row['status']=='tool_error':raise ValueError('MCP tool returned isError')
        state['status']='complete'
    except Exception as error:
        state.update(status='failed',error=type(error).__name__+': '+str(error))
        if plan.get('participant'):print(json.dumps({'gateway_error':state['error']}),flush=True)
    finally:
        if proc:
            proc.stdin.close()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            state['server_exit']=proc.returncode
        if server:
            server.shutdown();server.server_close()
            (receipt/'http.json').write_text(json.dumps(fixture.http_events,indent=2)+'\n')
        if stderr:stderr.close()
        save();wire.close()
    return state


if __name__=='__main__':
    import sys
    result=session(json.loads(Path('/frozen/plan.json').read_text()))
    sys.exit(0 if result['status']=='complete' else 1)
