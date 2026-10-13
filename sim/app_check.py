"""Read-only app visits, readable results, and an optional bounded deeper report."""
from __future__ import annotations
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit
from sim import ROOT, tool_trial

TARGETS = {
 'strive': {'name':'STRIVE','url':'https://striverun.app/','job':'Find how to bring in and preview your work.'},
 'favour': {'name':'FAVOUR','url':'http://127.0.0.1:3470/','job':'Find a project to try, then understand the next step.','local_candidate':True},
 'labs': {'name':'Oscar Labs','url':'https://oscar-labs.vercel.app/','job':'Find a story, read it, and return to the collection.'},
 'tokens': {'name':'Token tool','url':'http://127.0.0.1:58620/','job':'Find the cost view and understand what its numbers cover.'},
}

MEDIA=re.compile(r'step-[0-9]{2}\.png|v-[a-z]{2,12}-(t[1-3]-)?[0-9]{2}\.png')
NO_VISITORS_NOTE='A basic check has no test visitors, so it cannot say where a person gets stuck. Start a full run for that.'

def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def folder(ws, run_id):
 if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{24}',run_id):raise ValueError('That visit could not be found.')
 return ws.root/'app-checks'/run_id

def read(ws, run_id):
 p=folder(ws,run_id); result=tool_trial.read(p/'result.json')
 result['report_ready']=(p/'agent-report.json').exists()
 if (p/'classification.json').exists():result['control']=tool_trial.read(p/'classification.json').get('control',False)
 if result['report_ready']:result['agent_report']=report_read(p,'agent-report.json')
 if (p/'research-report.json').exists():result['research_report']=report_read(p,'research-report.json')
 if (p/'superseded.json').exists():
  # A superseded run keeps its files, but none of its counts or verdicts are served.
  result['superseded']=tool_trial.read(p/'superseded.json')
  for k in ('counts','visitors','tries','findings','fixes','sceptic','set_aside','control_result','rounds','spend'):result.pop(k,None)
  result['headline']=result['verdict']='Superseded. Its completion counts are withdrawn.'
 return result

def report_read(p, filename):
 out=tool_trial.read(p/filename)
 review=p/filename.replace('.json','-review.json')
 if review.exists():out['review']=tool_trial.read(review)
 return out

def listing(ws):
 root=ws.root/'app-checks'
 rows=[read(ws,p.name) for p in root.glob('*') if p.is_dir() and (p/'result.json').exists()]
 return {'targets':TARGETS,'runs':sorted(rows,key=lambda r:r.get('finished_at',r['started_at']),reverse=True)}

def start(ws, body):
 raw=body.get('url','');mode=body.get('mode','quick')
 if not isinstance(raw,str):raise ValueError('Paste one app link.')
 raw=raw.strip()
 if mode not in ('quick','full','swarm'):raise ValueError('Choose a basic check or a full run.')
 if not isinstance(raw,str) or len(raw)>400:raise ValueError('Paste one app link.')
 key=next((k for k,t in TARGETS.items() if raw.rstrip('/')==t['url'].rstrip('/')),None)
 u=urlsplit(raw)
 if u.username or u.password or u.query or u.fragment:raise ValueError('Use an app link without passwords, a query or a fragment.')
 if u.scheme not in ('https','http') or not u.hostname:raise ValueError('Paste a working app link, or a GitHub repository link.')
 if u.scheme=='http' and u.hostname not in ('localhost','127.0.0.1'):raise ValueError('Use HTTPS for a public app.')
 if u.hostname=='github.com':
  key='repo';target={'name':u.path.strip('/'),'url':raw,'job':'Open the app from its source.'}
 elif key:target=TARGETS[key]
 else:
  if u.hostname in ('169.254.169.254','0.0.0.0','::1'):raise ValueError('Choose an app address.')
  target={'name':u.hostname,'url':raw,'job':'Open the app and find a clear first step.'};key='custom'
 control=False
 if mode=='swarm':
  from sim import app_swarm
  if key=='repo':raise ValueError('That is a code link. Paste the address where the app runs so test visitors can open it.')
  control=app_swarm.is_control(raw)
  own=body.get('own_machine') is True
  if u.hostname in ('localhost','127.0.0.1') and not control and not own:raise ValueError('That is a local address. Tick "this is my own machine" to test it. Its page text goes to the model; nothing is written to it.')
  if u.hostname in ('169.254.169.254','0.0.0.0','::1'):raise ValueError('Choose an app address.')
  job=body.get('job');tries=3 if body.get('tries')==3 else 1
  if job is not None and (not isinstance(job,str) or not job.strip() or len(job)>200):raise ValueError('Say in one short line what people come to do.')
  # A saved result is replayed only for the same address, task, visitors, tries and setup.
  known=job.strip() if job else app_swarm.CONTROL_JOB if control else (app_swarm.kept_job(ws.root,raw) or {}).get('text')
  wanted=app_swarm.cache_key(raw,known,tries) if known else None
  if wanted and not body.get('fresh') and (ws.root/'app-checks').exists():
   same=[x for x in (tool_trial.read(q) for q in (ws.root/'app-checks').glob('*/result.json')) if x.get('status')=='complete' and x.get('cache_key')==wanted and not (ws.root/'app-checks'/x['id']/'superseded.json').exists()]
   if same:
    latest=max(same,key=lambda x:x.get('finished_at',''));return {**read(ws,latest['id']),'replayed':True}
  if not getattr(ws,'allow_app_swarm',False):raise ValueError('Test visitors are switched off in this session. A basic check still works.')
  app_swarm.require_key()
  if control:target={'name':'Planted broken app','url':raw,'job':'A control with a dead pricing link and docs behind sign-in.'};key='control'
 root=ws.root/'app-checks';root.mkdir(exist_ok=True)
 active=[tool_trial.read(p) for p in root.glob('*/result.json') if tool_trial.read(p).get('status') in ('queued','running')]
 if active:raise ValueError('One visit is already running. Let it finish before starting another.')
 run_id=secrets.token_hex(12);p=folder(ws,run_id);p.mkdir(mode=0o700)
 result={'id':run_id,'target':key,'name':target['name'],'url':raw,'job':target['job'],'mode':mode,'status':'queued','started_at':stamp(),'steps':[],'checks':[],'fixes':[],'limitations':[],'model_calls':0,'model_cost_usd':0,'scope':'Read-only browser visit, not a real human user study.'}
 if control:result['control']=True
 if mode=='swarm':
  result['tries_planned']=tries;result['own_machine']=own
  if job:result['job']={'text':job.strip(),'source':'fixed' if control and job.strip()==app_swarm.CONTROL_JOB else 'model' if (app_swarm.kept_job(ws.root,raw) or {}).get('text')==job.strip() else 'you'}
  if wanted:result['cache_key']=wanted
 tool_trial.dump(p/'result.json',result)
 log=(p/'worker.log').open('w');subprocess.Popen([sys.executable,'-m','sim.app_check','swarm' if mode=='swarm' else 'visit',str(p)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);log.close()
 return result

def job(ws, body):
 """Before a full run: a saved run for this address, or the model's one-line reading of what people come to do."""
 raw=body.get('url','')
 if not isinstance(raw,str) or not raw.strip() or len(raw)>400:raise ValueError('Paste one app link.')
 raw=raw.strip();u=urlsplit(raw)
 from sim import app_swarm
 if u.username or u.password or u.query or u.fragment:raise ValueError('Use an app link without passwords, a query or a fragment.')
 if u.scheme not in ('https','http') or not u.hostname or u.hostname=='github.com':raise ValueError('Paste the address where the app runs.')
 if u.scheme=='http' and u.hostname not in ('localhost','127.0.0.1'):raise ValueError('Use HTTPS for a public app.')
 control=app_swarm.is_control(raw)
 if u.hostname in ('localhost','127.0.0.1') and not control and body.get('own_machine') is not True:raise ValueError('That is a local address. Tick "this is my own machine" to test it. Its page text goes to the model; nothing is written to it.')
 saved=[]
 if (ws.root/'app-checks').exists():
  saved=[{'id':x['id'],'job':x['job'].get('text') if isinstance(x.get('job'),dict) else x.get('job'),'tries':x.get('tries_planned',1),'headline':x.get('headline'),'finished_at':x.get('finished_at')} for x in (tool_trial.read(q) for q in (ws.root/'app-checks').glob('*/result.json')) if x.get('mode')=='swarm' and x.get('status')=='complete' and x.get('url','').rstrip('/')==raw.rstrip('/')]
 if control:return {'text':app_swarm.CONTROL_JOB,'what':'A small app we planted with a dead pricing link and docs behind sign-in.','source':'fixed','pages_read':[raw],'saved':saved}
 if not getattr(ws,'allow_app_swarm',False):raise ValueError('Test visitors are switched off in this session. A basic check still works.')
 app_swarm.require_key()
 found=app_swarm.discover_job(ws.root,raw)
 return {**found,'needs_write':app_swarm.needs_write(found.get('text','')),'saved':saved}

def visit(p):
 from playwright.sync_api import sync_playwright
 p=Path(p);r=tool_trial.read(p/'result.json');start_time=time.monotonic();lock=(p.parent/'.visit.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
 r['status']='running';r['browser']='Playwright Chromium';tool_trial.dump(p/'result.json',r)
 failures=[];requests=[];console=[];blocked=[]
 def save():tool_trial.dump(p/'result.json',r)
 def step(label, action, expected=None):
  n=len(r['steps'])+1;t=time.monotonic();row={'order':n,'label':label,'started_at':stamp(),'status':'running'};r['steps'].append(row);save()
  try:
   response=action();page.wait_for_timeout(700)
   if label=='Open the app':
    try:page.wait_for_function('document.body.innerText.trim().length > 80',timeout=10000)
    except Exception:pass
   text=page.locator('body').inner_text();row.update({'status':'passed','url':page.url,'title':page.title(),'visible_characters':len(text)})
   if response is not None and hasattr(response,'status'):
    row['http_status']=response.status
    if response.status>=400:row['status']='failed';row['reason']='The page answered with HTTP '+str(response.status)+'.'
   if expected and not expected(text):row['status']='failed';row['reason']='The expected reading view did not appear.'
   (p/f'step-{n:02d}.txt').write_text(text)
   page.screenshot(path=str(p/f'step-{n:02d}.png'),full_page=False);row['screenshot']=f'step-{n:02d}.png'
  except Exception as e:row.update({'status':'failed','reason':type(e).__name__+': '+str(e)[:250]})
  row['elapsed_ms']=round((time.monotonic()-t)*1000);save();return row
 if r['target']=='repo':
  r.update({'status':'complete','verdict':'Could not try it','summary':'A source repository is not a running app. Add its preview link so we can try the first visit.','checks':[{'label':'App opens','status':'not_run','reason':'Only source was supplied.'}],'counts':{'passed':0,'failed':0,'not_run':1},'fixes':[],'fixes_note':'Nothing was opened, so there is nothing to fix yet. Paste the address where the app runs.','limitations':['No source was installed or executed.'],'elapsed_ms':round((time.monotonic()-start_time)*1000),'finished_at':stamp()});save();return
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},record_video_dir=str(p/'video'),record_video_size={'width':1440,'height':1000})
   def route(rt):
    req=rt.request
    if req.method not in ('GET','HEAD','OPTIONS'):
     blocked.append({'method':req.method,'url':urlsplit(req.url)._replace(query='',fragment='').geturl()});rt.abort();return
    requests.append({'method':req.method,'url':urlsplit(req.url)._replace(query='',fragment='').geturl()});rt.continue_()
   context.route('**/*',route);page=context.new_page();page.set_default_timeout(15000)
   page.on('pageerror',lambda e:console.append(str(e)[:300]));page.on('response',lambda response:failures.append({'url':urlsplit(response.url)._replace(query='',fragment='').geturl(),'status':response.status}) if response.status>=400 else None)
   first=step('Open the app',lambda:page.goto(r['url'],wait_until='domcontentloaded',timeout=45000),lambda text:len(text.strip())>80)
   r['checks'].append({'label':'App opens','status':first['status']})
   key=r['target'];main=None
   if first['status']=='passed':
    if key=='strive':
     main=step('Find how to bring in your work',lambda:page.goto(r['url'].rstrip('/')+'/install',wait_until='domcontentloaded'),lambda text:any(x in text.lower() for x in ['install','capture','cursor']))
     r['limitations'].append('This visit did not upload or save a run. A complete private preview remains untested here.')
    elif key=='favour':
     def explore():
      b=page.get_by_role('button',name=re.compile('Explore Welcome',re.I))
      if b.count():b.first.click()
      else:
       a=page.get_by_role('link',name=re.compile('Explore Welcome',re.I))
       if a.count():a.first.click()
       else:raise ValueError('The expected first-visit button was not available.')
     main=step('Find the first project',explore)
     r['limitations'].append('Local preview only. No terms accepted, review submitted, vote, payment or store write was made.')
    elif key=='labs':
     links=page.locator('a').evaluate_all("es=>es.map(e=>({href:e.href,text:e.innerText.trim()}))")
     choices=[x for x in links if urlsplit(x['href']).hostname==urlsplit(r['url']).hostname and urlsplit(x['href']).path not in ('/','/about','/feed','/subscribe') and len(x['text'])>15]
     if not choices:raise ValueError('No same-site story link was visible.')
     article=choices[0]['href'];r['selected_story']={'url':article,'link_text':choices[0]['text'][:200]}
     main=step('Open the selected story',lambda:page.locator('a').filter(has_text=choices[0]['text'].split('\n')[0]).first.click(),lambda text:len(text)>250 and not ('404' in text[:160]))
     if r['mode']=='full':
      step('Return to the collection',lambda:page.go_back(wait_until='domcontentloaded'),lambda text:len(text)>80)
      step('Open the same story again',lambda:page.locator('a').filter(has_text=choices[0]['text'].split('\n')[0]).first.click(),lambda text:len(text)>250)
      step('Reload and keep reading',lambda:page.reload(wait_until='domcontentloaded'),lambda text:len(text)>250)
    elif key=='tokens':
     main=step('Open the cost view',lambda:page.goto(r['url'].rstrip('/')+'/spend.html',wait_until='domcontentloaded'),lambda text:any(x in text.lower() for x in ['cost','spend','token']))
     r['limitations'].append('The numbers are existing local records. This visit did not refresh providers or verify invoices.')
    else:
     links=page.locator('a').evaluate_all("es=>es.map(e=>({href:e.href,text:e.innerText.trim()}))")
     links=[x for x in links if urlsplit(x['href']).hostname==urlsplit(r['url']).hostname and x['text'] and not re.search('delete|publish|submit|sign.out|pay|checkout',x['text'],re.I) and x['href']!=page.url]
     if links:main=step('Try the first visible reading path',lambda:page.goto(links[0]['href'],wait_until='domcontentloaded'),lambda text:len(text)>80)
     else:r['limitations'].append('No safe reading link was visible. Buttons and protected actions were not exercised.')
   if main:r['checks'].append({'label':'First link opens','status':main['status']})
   else:r['checks'].append({'label':'First link opens','status':'not_run'})
   r['checks'].append({'label':'No script errors','status':'passed' if not console else 'failed','count':len(console)})
   r['checks'].append({'label':'Come back to the same page','status':'passed','reason':''} if r['mode']=='full' and key=='labs' and all(x['status']=='passed' for x in r['steps']) else {'label':'Come back to the same page','status':'not_run','reason':'Only set up for one example app. A full run does not use this check.'})
   context.close();browser.close()
 except Exception as e:r['error']=type(e).__name__+': '+str(e)[:300]
 passed=sum(c['status']=='passed' for c in r['checks']);failed=sum(c['status']=='failed' for c in r['checks']);not_run=sum(c['status']=='not_run' for c in r['checks'])
 r['verdict']='Needs work' if failed or r.get('error') else 'Reading path works' if r['target']=='labs' and not not_run else 'Partly checked'
 r['summary']={'strive':'The install path was opened. Bringing in and saving real work was not tested.','favour':'The first visit was tried on the local candidate. Protected review steps were left untouched.','labs':'The story-reading path was tried. This result applies to the selected story and this visit.','tokens':'The local cost view was tried. Existing numbers are not proof of current invoices.'}.get(r['target'],'The app was opened and a safe reading path was tried.')
 if r.get('error'):r['summary']='The visit stopped: '+r['error']
 r['fixes']=[];r['fixes_note']=NO_VISITORS_NOTE
 r.update({'status':'complete','finished_at':stamp(),'elapsed_ms':round((time.monotonic()-start_time)*1000),'counts':{'passed':passed,'failed':failed,'not_run':not_run},'raw':{'page_errors':console,'failed_responses':failures,'read_requests':requests,'blocked_write_requests':blocked},'limitations':r['limitations']+['This basic check used no model and no test visitors.']})
 tool_trial.dump(p/'result.json',r);lock.close()


def report(ws, body):
 p=folder(ws,body.get('id'));r=read(ws,p.name)
 kind=body.get('kind','full')
 if kind not in ('full','research'):raise ValueError('Choose the visit report or the comparison report.')
 filename='research-report.json' if kind=='research' else 'agent-report.json'
 if (p/filename).exists():return report_read(p,filename)
 if not getattr(ws,'allow_app_report',False):raise ValueError('The deeper review is off in this local session.')
 if r['status']!='complete':raise ValueError('Let the visit finish before fetching its report.')
 from sim import hosted_cost,app_swarm
 from sim.adapters import tokenfactory
 app_swarm.ensure_account()
 from sim.adapters.openai_compat import ChatClient
 from decimal import Decimal
 account=json.loads(hosted_cost.RECORD.read_text());total=hosted_cost.prior_total()+sum((Decimal(str(x['accounted_usd'])) for x in account['runs'].values()),Decimal(0))
 if total+hosted_cost.worst_case(1)>Decimal(8):raise ValueError('The reporting stop was reached. The next review needs a reconciled allowance.')
 safe={'product':r['name'],'job':r['job'],'selection_scope':'One eligible story was selected; the number of visible choices was not measured.','verdict':r['verdict'],'steps':[{'label':s['label'],'status':s['status'],'elapsed_ms':s['elapsed_ms']} for s in r['steps']],'checks':r['checks'],'suggested_fixes':r['fixes'],'limitations':r['limitations']}
 if kind=='research':
  latest={}
  for row in listing(ws)['runs']:
   if row['status']=='complete' and row['target'] in TARGETS and row['target'] not in latest:
    latest[row['target']]={'product':row['name'],'verdict':row['verdict'],'checks':row['checks'],'limitations':row['limitations'],'elapsed_ms':row['elapsed_ms']}
  safe={'comparison':list(latest.values()),'study_scope':'Four author-operated read-only app visits. No outside human users. Missing steps remain untested. The initial FAVOUR attempt was retained; the newest follow-up controls hydration readiness.'}
 messages=[{'role':'system','content':'Write a grounded review in at most 160 words. Distinguish observed screens, untested actions, and three proposed next checks. One selected story does not mean only one was visible. FAVOUR returned a page shell but no meaningful reading view within ten seconds; the cause is unknown. Never call this a crash or proof its core is broken. No actual human used these visits. No stress or phone test of the products occurred. Do not invent feedback, defect causes, prices or unobserved behavior. For a comparison, use one short paragraph per product. Do not include a roadmap.'},{'role':'user','content':json.dumps(safe)}]
 if len(json.dumps(messages).encode())>hosted_cost.MAX_PROMPT_BYTES:raise ValueError('The report is too large.')
 key=str(p/('research-report-grounded-v2' if kind=='research' else 'agent-report-grounded-v2'));hosted_cost.reserve(key,1,hosted_cost.MODEL);events=[];out=None;usage_settled=False
 try:
  client=ChatClient(base_url=tokenfactory.BASE_URL,model=hosted_cost.MODEL,label='RUNTIME',api_key=tokenfactory.load_key(),record=events.append)
  reply=client.chat(messages,temperature=0,seed=0,max_tokens=1024,chat_template_kwargs={'enable_thinking':False})
  cost=hosted_cost.settle(key,reply.usage,True);usage_settled=True
  if reply.model!=hosted_cost.MODEL or not reply.text.strip():raise ValueError('The report returned no verified model response.')
  out={'status':'complete','text':reply.text,'model':reply.model,'model_calls':1,'usage':reply.usage,'listed_rate_estimate_usd':cost['accounted_usd'],'provider_invoice_usd':None,'scope':'Model review of recorded browser observations; the model did not browse or represent human users.','at':stamp(),'kind':kind,'finish_reason':reply.finish_reason,'review_required':True};tool_trial.dump(p/filename,out);return out
 finally:
  if out is None and not usage_settled:hosted_cost.settle(key,{},False)
  tool_trial.dump(p/('research-provider-events-grounded-v2.json' if kind=='research' else 'report-provider-events-grounded-v2.json'),events)

if __name__=='__main__':
 if len(sys.argv)!=3 or sys.argv[1] not in ('visit','swarm'):raise SystemExit('Use visit|swarm <result-directory>.')
 if sys.argv[1]=='visit':visit(sys.argv[2])
 else:
  from sim import app_swarm
  try:app_swarm.run(sys.argv[2])
  except Exception as e:
   r=tool_trial.read(Path(sys.argv[2])/'result.json');r.update({'status':'complete','finished_at':stamp(),'error':type(e).__name__+': '+str(e)[:300],'headline':'The run could not finish.','verdict':'The run could not finish.'});tool_trial.dump(Path(sys.argv[2])/'result.json',r);raise
