"""Runs inside local Docker as root. Agents can invoke tools, never edit audit records."""
import json
import os
from pathlib import Path
import socket
import subprocess


def main():
    config=json.loads(Path('/control/gateway.json').read_text())
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    server.bind('/run/tool.sock');os.chmod('/run/tool.sock',0o666);server.listen(8)
    calls=0
    while True:
        conn,_=server.accept();conn.settimeout(35)
        with conn:
            data=b''
            while not data.endswith(b'\n') and len(data)<=10000:
                chunk=conn.recv(4096)
                if not chunk:break
                data+=chunk
            try:
                args=json.loads(data)
                if not isinstance(args,list) or len(args)>80 or any(not isinstance(x,str) or '\0' in x for x in args):raise ValueError('Expected bounded argv strings.')
                if sum(map(len,args))>8000:raise ValueError('Arguments too long.')
                if calls>=config['max_invocations']:raise ValueError('Registered tool invocation budget exhausted.')
                calls+=1
                try:
                    result=subprocess.run(config['command']+args,cwd='/work',capture_output=True,timeout=30,
                                          user=1000,group=1000,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
                    row={'args':args,'returncode':result.returncode,'output':(result.stdout+result.stderr).decode(errors='replace')[:20000]}
                except subprocess.TimeoutExpired:
                    row={'args':args,'returncode':124,'output':'Tool invocation timed out.'}
                # The agent and tool share artifact ownership; /control remains root-only.
                with open('/control/invocations.jsonl','a') as stream:
                    stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
                conn.sendall((json.dumps(row)+'\n').encode())
            except Exception as e:
                conn.sendall((json.dumps({'returncode':125,'output':'Gateway refused: '+type(e).__name__})+'\n').encode())

if __name__=='__main__':main()
