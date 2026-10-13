"""First Users local front door and keyless hosted sample mode.

Run: python -m sim.first_users --store ../first-users-private --port 3899
Sample: append --sample. Models: explicit --allow-models, separate cost account.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from http.cookies import SimpleCookie
import argparse,html,json,os,re,secrets,subprocess,sys,threading,time,signal
from sim import app_swarm,task_contract,first_users_payment
from sim.check_queue import Queue
from sim.favour_handoff import project_draft

WEB=Path(__file__).resolve().parents[1]/'workspace'

class App:
    def __init__(self,store,*,sample=False,models=False):
        self.store=Path(store);self.store.mkdir(parents=True,exist_ok=True);self.sample=sample;self.models=models and not sample
        self.queue=Queue(self.store/'queue.sqlite',quota=10,lease_seconds=30,max_attempts=1,max_total=20 if sample else None)
        with self.queue.tx() as db:db.execute('CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,data TEXT NOT NULL)')
        self.stop=threading.Event();self.worker=threading.Thread(target=self.work,daemon=True);self.worker.start()
        self.port=None

    def draft(self,tenant,key):
        with self.queue.tx() as db:
            row=db.execute('SELECT data FROM drafts WHERE id=? AND tenant=?',(key,tenant)).fetchone()
            return json.loads(row[0]) if row else None

    def save(self,tenant,key,data):
        with self.queue.tx() as db:db.execute('INSERT INTO drafts VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(key,tenant,json.dumps(data)))

    def work(self):
        while not self.stop.wait(.1):
            job=self.queue.lease()
            if not job:continue
            folder=self.store/'checks'/job['id'];folder.mkdir(parents=True,exist_ok=True)
            p=job['payload'];result={'id':job['id'],'target':'custom','url':p['url'],'name':'First Users check','job':{'text':p['task'],'source':'builder-approved'},'mode':'swarm' if p['model'] else 'quick','status':'queued','started_at':app_swarm.stamp(),'tries_planned':1,'steps':[],'checks':[],'fixes':[],'limitations':[],'model_calls':0,'model_cost_usd':0}
            (folder/'result.json').write_text(json.dumps(result));heartbeat_stop=threading.Event()
            def beat():
                while not heartbeat_stop.wait(5):
                    if not self.queue.heartbeat(job['id'],job['fence']):break
            threading.Thread(target=beat,daemon=True).start();proc=None
            try:
                module='sim.app_check'; action='swarm' if p['model'] else 'visit'
                env=dict(os.environ)
                if not p['model']:env={k:v for k,v in env.items() if not any(x in k for x in ('KEY','SECRET','TOKEN'))}
                proc=subprocess.Popen([sys.executable,'-m',module,action,str(folder)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                try:proc.wait(timeout=180 if p['model'] else 45)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait();raise ValueError('Check deadline reached; no result accepted.')
                r=json.loads((folder/'result.json').read_text())
                if proc.returncode or r.get('status')!='complete':raise ValueError('The browser check did not finish.')
                view=self.clean_report(r,p)
                cost=int(round((float(r.get('model_cost_usd',0))+float(r.get('spend',{}).get('held_reservation_usd',0)))*1000000))
                self.queue.settle(job['id'],job['fence'],view,cost_microusd=cost)
            except Exception as e:self.queue.settle(job['id'],job['fence'],{'error':str(e)[:160]},failed=True)
            finally:heartbeat_stop.set()

    def clean_report(self,r,p):
        screens=[]
        for s in r.get('steps',[]):
            if s.get('screenshot'):screens.append({'image':s['screenshot'],'label':s.get('title') or s.get('status') or 'Observed page'})
        for group in r.get('tries',[]):
            for visitor in group:
                for s in visitor.get('steps',[]):
                    image=(s.get('hit') or {}).get('screenshot') or s.get('screenshot')
                    if image:screens.append({'image':image,'label':visitor['name']+' · '+str(s.get('status'))})
        return {'task':p['task'],'contract':task_contract.compile_task(p['task']).payload(),
                'scope':'Real model visitors; models are not people.' if p['model'] else 'Fresh basic browser check, not task completion or human validation.',
                'checks':r.get('checks',[]),'headline':r.get('headline') or r.get('verdict') or 'Recorded check',
                'screens':screens[:30],'limitations':r.get('limitations',[]),
                'model_calls':r.get('model_calls',0),'completion_claim':'No complete-task claim from a basic check.' if not p['model'] else 'Inspect recorded evidence; model completion judgements can be wrong.'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    @property
    def app(self):return self.server.app
    def tenant(self):
        cookie=SimpleCookie(self.headers.get('Cookie',''));value=cookie.get('first_users')
        if value and re.fullmatch('[a-f0-9]{48}',value.value):return value.value
        if not hasattr(self,'new_tenant'):self.new_tenant=secrets.token_hex(24)
        return self.new_tenant
    def send(self,status,value,kind='application/json'):
        data=value if isinstance(value,bytes) else json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if hasattr(self,'new_tenant'):self.send_header('Set-Cookie','first_users='+self.new_tenant+'; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers();self.wfile.write(data)
    def public_base(self):
        # Only operator configuration can select a checkout return origin.
        return os.environ.get('FIRST_USERS_PUBLIC_ORIGIN',f'http://127.0.0.1:{self.app.port}').rstrip('/')
    def do_GET(self):
        self.tenant();path=urlsplit(self.path).path
        files={'/':'first-users.html','/first-users.js':'first-users.js','/first-users.css':'first-users.css'}
        if path in files:return self.send(200,(WEB/files[path]).read_bytes(),{'/':'text/html','/first-users.js':'application/javascript','/first-users.css':'text/css'}[path])
        if path=='/health':return self.send(200,{'ready':True,'sample_mode':self.app.sample,'models_enabled':self.app.models,'payment_mode':'PRACTICE_NO_CHARGE' if self.app.sample or not first_users_payment.test_key() else 'STRIPE_TEST','test_key_place':first_users_payment.KEY_PLACE})
        if path.startswith('/samples/'):
            if path=='/samples/broken/help':return self.send(404,b'<h1>404</h1><p>The planted guide is missing.</p>','text/html')
            if path not in ('/samples/working','/samples/working/help','/samples/broken'):return self.send(404,{'error':'Not found'})
            content='<h1>Getting started</h1><p>Keep one collection per project. Read a note before changing it. This public sample needs no account and does not save data.</p>' if path.endswith('/help') else '<h1>Notes collection</h1><p>Open our guide to learn how to organise your notes. This is a controlled sample rather than a customer result.</p>'
            stem='/samples/broken' if 'broken' in path else '/samples/working'
            return self.send(200,('<html><title>Reading sample</title><main>'+content+f'<a href="{stem}/help">Read the guide</a><p><a href="{stem}">Back to the collection</a></p></main></html>').encode(),'text/html')
        if path.startswith('/api/draft/'):
            r=self.app.draft(self.tenant(),path.rsplit('/',1)[-1]);return self.send(200,r) if r else self.send(404,{'error':'Draft not found'})
        if path.startswith('/api/reports/'):
            r=self.app.queue.get(self.tenant(),path.rsplit('/',1)[-1]);return self.send(200,r) if r else self.send(404,{'error':'Report not found'})
        if path.startswith('/api/shared/'):
            r=self.app.queue.shared(path.rsplit('/',1)[-1]);return self.send(200,r) if r else self.send(404,{'error':'Share expired or revoked'})
        if path.startswith('/screen/'):
            bits=path.split('/');key=bits[2] if len(bits)==4 else '';name=bits[3] if len(bits)==4 else ''
            report=self.app.queue.get(self.tenant(),key)
            if not report:
                # Shared screen uses the capability rather than a job identity.
                report=self.app.queue.shared(key)
            allowed=[s['image'] for s in ((report or {}).get('result') or {}).get('screens',[])]
            if name in allowed and re.fullmatch(r'[a-zA-Z0-9_-]+\.png',name):
                f=self.app.store/'checks'/report['id']/name
                if f.is_file() and not f.is_symlink():return self.send(200,f.read_bytes(),'image/png')
        return self.send(404,{'error':'Not found'})
    def do_POST(self):
        origin=self.headers.get('Origin');host=self.headers.get('Host')
        if not origin or urlsplit(origin).netloc!=host:return self.send(403,{'error':'Same-origin request required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<8000:raise ValueError('Small request required.')
            body=json.loads(self.rfile.read(size));tenant=self.tenant();path=urlsplit(self.path).path
            if path=='/api/drafts':
                url=body.get('url','').strip();u=urlsplit(url)
                if self.app.sample:
                    sample=body.get('sample')
                    if sample not in ('working','broken'):raise ValueError('Choose a bundled sample. Hosted caller URLs are disabled.')
                    url=f'http://127.0.0.1:{self.app.port}/samples/{sample}'
                elif u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
                    raise ValueError('Use an HTTP address without credentials, query or fragment. Local mode is for authorized targets only.')
                task=body.get('task','Read the getting started guide')
                contract=task_contract.compile_task(task);key=secrets.token_hex(16);draft={'id':key,'url':url,'task':task,'contract':contract.payload(),'approved':False,'practice_ack':False,'payment':None}
                self.app.save(tenant,key,draft);return self.send(200,draft)
            key=body.get('id');d=self.app.draft(tenant,key)
            if not d:raise ValueError('Your draft was not found.')
            if path=='/api/confirm':
                d['task']=body['task'];d['contract']=task_contract.compile_task(d['task']).payload()
                if d['contract']['intent']=='unknown':raise ValueError('Clarify the task before continuing.')
                d['approved']=True;self.app.save(tenant,key,d);return self.send(200,d)
            if path=='/api/payment':
                if not d['approved']:raise ValueError('Confirm the task first.')
                d['payment']={'mode':'PRACTICE_NO_CHARGE','paid':False,'amount_eur':19,'key_place':first_users_payment.KEY_PLACE} if self.app.sample else first_users_payment.begin(key,self.public_base())
                self.app.save(tenant,key,d);return self.send(200,d['payment'])
            if path=='/api/run':
                if not d['approved'] or not d['payment']:raise ValueError('Confirm the task and payment step first.')
                if d['payment']['mode']=='PRACTICE_NO_CHARGE':
                    if body.get('practice_ack') is not True:raise ValueError('Acknowledge practice mode; this is not payment.')
                elif not first_users_payment.verified(d['payment']['session'],key):raise ValueError('Stripe test payment not confirmed by server.')
                use_model=body.get('model') is True
                if use_model and not self.app.models:raise ValueError('Model calls require explicit operator enablement; unavailable in sample mode.')
                id=self.app.queue.enqueue(tenant,key,{'url':d['url'],'task':d['task'],'model':use_model});return self.send(200,{'id':id,'state':'queued','charged':False})
            if path=='/api/share':return self.send(200,{'capability':self.app.queue.share(tenant,body['report_id']),'expires_days':7})
            if path=='/api/handoff':return self.send(200,project_draft(d['url'],d['task']))
            return self.send(404,{'error':'Not found'})
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:return self.send(400,{'error':str(e)[:180]})

def main():
    p=argparse.ArgumentParser();p.add_argument('--store',required=True);p.add_argument('--port',type=int,default=3899);p.add_argument('--sample',action='store_true');p.add_argument('--allow-models',action='store_true');a=p.parse_args()
    app=App(a.store,sample=a.sample,models=a.allow_models);server=ThreadingHTTPServer(('0.0.0.0' if a.sample else '127.0.0.1',a.port),Handler);app.port=server.server_port;server.app=app
    print(f'First Users on port {app.port}; sample={app.sample}; models={app.models}; no live payment.',flush=True)
    try:server.serve_forever()
    finally:app.stop.set();server.server_close()
if __name__=='__main__':main()
