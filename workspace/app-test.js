'use strict';
const $=s=>document.querySelector(s);
let token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem('workspace-token')||'';
if(token){sessionStorage.setItem('workspace-token',token);history.replaceState(null,'',location.pathname+location.search);}
let current=null,timer=null,playTimer=null,all=[];
const SVG='http://www.w3.org/2000/svg';
const calm=matchMedia('(prefers-reduced-motion: reduce)').matches;
async function api(path,body){const r=await fetch('/api/app-check/'+path,{method:body?'POST':'GET',headers:{'X-Workspace-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.error);return d;}
function node(t,text,parent,cls){const e=document.createElement(t);if(text!==''&&text!=null)e.textContent=text;if(cls)e.className=cls;if(parent)parent.append(e);return e;}
function svg(t,attrs,parent,text){const e=document.createElementNS(SVG,t);for(const k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;if(parent)parent.append(e);return e;}
const secs=ms=>(ms/1000).toFixed(1)+'s';
const blobs=new Map();
async function photo(id,file,img){if(!file||img.dataset.file===id+file)return;img.dataset.file=id+file;let url=blobs.get(id+file);if(url){img.src=url;return;}img.classList.add('loading');if(!url){const r=await fetch('/api/app-check/media/'+id+'/'+file,{headers:{'X-Workspace-Token':token}});if(!r.ok)return;url=URL.createObjectURL(await r.blob());blobs.set(id+file,url);}if(img.dataset.file===id+file){img.src=url;img.classList.remove('loading');}}

const OUTCOME={got_there:'Job completed',stuck:'Got stuck',left_app:'Left for another site',not_finished:'Did not finish',claimed:'Said done, not confirmed',screen_only:'Screen confirmed, steps missing',reached_start:'Reached the start'};
function did(s){const t=s.target_text?'“'+s.target_text.slice(0,38)+'”':'';
 if(s.status==='thinking')return 'Reading the page';
 if(s.status==='got_there')return 'Completed the job here';
 if(s.status==='reached_start')return 'Reached the screen where it starts';
 if(s.status==='left_app')return 'Left for '+(s.left_for||'another site');
 if(s.status==='error_page')return 'Clicked '+t+' and got an error page';
 if(s.status==='not_allowed')return 'Tried '+t+'. It was not open to a visitor';
 if(s.status==='stuck')return s.gave_up?'Gave up here':'Stuck here';
 if(s.status==='confused')return 'Lost the thread';
 if(s.action==='click')return s.status==='no_effect'?'Clicked, nothing changed':'Clicked '+t;
 if(s.action==='scroll')return s.status==='no_effect'?'Looked for more, found the end':'Scrolled down';
 if(s.action==='back')return s.status==='no_effect'?'Tried to go back':'Went back';
 return 'Looked around';}
function count(el,to){if(calm||!to){el.textContent=to;return;}const t0=performance.now();(function tick(now){const k=Math.min(1,(now-t0)/450);el.textContent=Math.round(to*k);if(k<1)requestAnimationFrame(tick);})(t0);}

function show(r){clearInterval(playTimer);const same=current&&current.id===r.id;current=r;const box=$('#result');box.replaceChildren();const card=node('article','',box,'result');if(same)card.style.animation='none';
 if(r.superseded){node('p',r.name,card,'eyebrow');node('h2','This run is superseded',card,'verdict');node('p',r.superseded.why+' Its completion counts are withdrawn and are not shown.',card);const o=all.find(x=>x.id===r.superseded.by);if(o){const b=node('button','Open the run that replaces it →',card,'quiet');b.type='button';b.onclick=()=>show(o);}}
 else if(r.mode==='swarm')showRun(r,card);else showBasic(r,card);
 history.replaceState(null,'',location.pathname+'?visit='+r.id);for(const b of document.querySelectorAll('#history button'))b.classList.toggle('selected',b.dataset.id===r.id);}

const picked=new Map();
const VERDICT={gets_through:'Gets the job done',gets_stuck:'Gets stuck',unclear:'No clear result',reaches_start:'Reaches the start',sceptic:'Own question'};
function showRun(r,card){const live=r.status!=='complete',n=r.tries_planned||1,tries=r.tries||[],c=r.counts||{};
 let sel=picked.has(r.id)?picked.get(r.id):(live?Math.max(0,tries.length-1):0);if(sel>=tries.length)sel=Math.max(0,tries.length-1);
 const vs=tries[sel]||[],sum=r.visitors||[];
 if(r.control_result){const k=node('div','',card,'control');node('b',r.control_result.held?'Planted broken app: the run went red where it should.':'Planted broken app: the run did NOT catch the planted fault.',k);node('span','We built this small app with a dead pricing link. Every visitor sent to find the price must fail. '+r.control_result.failed_as_planted.length+' of '+r.control_result.must_fail.length+' did, in every try.',k);}
 const grid=node('div','',card,'verdict-grid'),left=node('div','',grid),right=node('figure','',grid);
 node('p',r.name+' · '+short(r.url).replace(/\/$/,'')+(r.own_machine?' · your own machine':''),left,'eyebrow');
 if(r.job?.text){const j=node('p','',left,'jobline');node('span','People come here to',j,'k');j.append(r.job.text+'. ');const guessed=r.job.source==='model';node('span',{you:'Task line set by you.',model:'Task guessed by the model, not checked by you.',fixed:'Fixed task for the planted app.',fallback:'We could not tell what visitors come to do. This is a general task. Edit the line and run again.'}[r.job.source]||'',j,guessed?'guess':'hint');}
 const h=node('h2','',left,'verdict');
 if(live)h.textContent=tries.length?(n>1?'Try '+tries.length+' of '+n+': ':'')+'five test visitors are on your app':'Reading your pages';
 else if(r.error&&!sum.length){h.textContent='The run could not finish.';node('p',r.error,left);}
 else{const wr=r.job?.needs_write,cut=wr?r.headline.indexOf('reads. ')+7:0;if(wr){const lm=node('p','',left,'limitline');node('b','Limit of this test',lm);lm.append(r.headline.slice(0,cut));left.append(h);}
  const rest=r.headline.slice(cut),k=wr?c.reaches_start:c.gets_through;const a=node('b','',h,k?'n-good':'n-bad');count(a,k||0);h.append(rest.replace(/^\d+/,''));}
 const top=(r.findings||[])[0];
 if(!live&&top){const f=node('div','',left,'first-fix');node('q',top.title,f);const e=top.kind==='different_places'?top.evidence.at(-1):top.evidence[0];node('span',e.name+', a test visitor. '+top.what_happened+(top.tries>1?' Seen in '+top.hits+' of '+top.tries+' tries.':''),f);const img=node('img','',right,'shot');img.alt='The screen where this test visitor stopped';photo(r.id,e.screenshot,img);node('figcaption','The screen where the '+lower(e.name)+' stopped. '+short(top.page),right);}
 else if(!live&&sum.length){const f=node('div','',left,'first-fix none');node('q',r.fixes_note||'Nobody got stuck.',f);let w=null,s=null;for(const t of tries)for(const v of t)if(!w&&v.outcome==='got_there'){w=v;s=v.steps.at(-1);}if(w){const img=node('img','',right,'shot');img.alt='The screen where a test visitor completed the job';photo(r.id,s.screenshot,img);node('figcaption','Where the '+lower(w.name)+' completed it: “'+(s.quote||'').replace(/\s+/g,' ').slice(0,110)+'”',right);}}
 else node('p','Each one tries the same job in its own way. Watch them below.',left);
 if(!live&&sum.length){const stats=node('div','',left,'stats');for(const [x,t] of [[c.visitors,'test visitors, plus one sceptic'],[c.sessions,'visits made'],[secs(r.elapsed_ms),'for the whole run'],[r.model_calls,'calls to the NVIDIA model']]){const s=node('div','',stats,'stat');const b=node('b','',s);typeof x==='number'?count(b,x):b.textContent=x;node('span',t,s);}
  const cr=node('p','',left,'credit');cr.append('Every step was chosen by NVIDIA Nemotron on Nebius Token Factory. ');const a=node('a','Open the agent report →',cr);a.href='/agent-report?visit='+r.id;}

 // Three states, kept apart, try by try.
 if(!live&&sum.length){const st=node('div','',card,'block');node('h3',r.job?.needs_write?'Said it found the start, start confirmed, task itself not tested':'Said done, screen confirmed, job completed',st);node('p','Three different things. A visitor can say it is done. A second check of that screen and its steps can agree, and must point at words on the screen. The job counts as completed only when the steps also show every part of the task.',st,'hint');
  const tb=node('table','',st,'states'),hd=node('tr','',tb);const wr=r.job?.needs_write;for(const t of ['Visitor',...tries.map((_,i)=>n>1?'Try '+(i+1):'The visit'),...(wr?['Said it found the start','Start screen confirmed','Task itself']:['Said done','Screen confirmed','Job completed']),'Over '+n+(n>1?' tries':' try')])node('th',t,hd);
  for(const v of sum){const tr=node('tr','',tb);const nm=node('td','',tr);const i=node('i','',nm,'sw');i.style.background=v.colour;nm.append(v.name);for(const o of v.outcomes)node('span',OUTCOME[o]||o,node('td','',tr),'tag '+o);for(const [i,x] of [v.claimed,v.screen_confirmed,v.confirmed].entries())node('td',wr&&i===2&&!v.sceptic?'not tested':x+' of '+n,tr,'num');node('span',VERDICT[v.verdict],node('td','',tr),'tag '+v.verdict);if(v.sceptic)tr.className='apart';}
  const tr=node('tr','',tb,'total');node('td','The '+c.visitors+' visitors on the task',tr);for(const _ of tries)node('td','',tr);for(const [i,x] of [c.claimed,c.screen_confirmed,c.confirmed].entries())node('td',wr&&i===2?'not tested':x+' of '+c.sessions,tr,'num');node('td',c.same_every_try+' of '+c.visitors+' ended the same way every try',tr);
  if(r.sceptic)node('p','The sceptic is counted apart. Its own question: '+lower(r.sceptic.goal)+' Answered in '+r.sceptic.answered+' of '+r.sceptic.tries+(r.sceptic.tries>1?' tries.':' try.'),st,'hint');
  if(wr)node('p','Why “not tested”: this task needs sign-in or saves something. The test visitors only read, so the most they can show is the screen where a signed-out person would begin.',st,'hint');}

 // The five little browsers: who is doing what.
 const wb=node('div','',card,'block');node('h3',live?'Happening now':'Watch the run again',wb);node('p',live?'Each screen is what that visitor sees right now.':'These are the saved screens. Playing them again costs nothing and opens nothing.',wb,'hint');
 if(tries.length>1){const sw=node('div','',wb,'tryswitch');tries.forEach((_,i)=>{const b=node('button','Try '+(i+1),sw,i===sel?'active':'');b.type='button';b.onclick=()=>{picked.set(r.id,i);show(r);};});}
 const board=node('div','',wb,'board'),seats=new Map();
 for(const v of vs){const s=node('div','',board,'seat'+(v.phone?' phone':''));const h4=node('h4','',s);node('i','',h4).style.background=v.colour;h4.append(v.name);const fr=node('div','',s,'frame');const img=node('img','',fr);img.alt='What the '+lower(v.name)+' sees';const now=node('p','',s,'now');seats.set(v.id,{img,now,v});}
 const total=Math.max(1,(r.rounds||[])[sel]?.elapsed_ms||1,...vs.map(v=>v.end_ms||0));
 function paint(t){for(const {img,now,v} of seats.values()){const past=v.steps.filter(s=>s.start_ms<=t);const s=past.at(-1);now.replaceChildren();
   if(!s){node('b',v.status==='waiting'?'Waiting to start':'Opening the app',now);continue;}
   photo(r.id,s.screenshot,img);const ended=v.outcome&&v.status==='complete'&&t>=(v.end_ms??Infinity);
   const going=!ended&&s===v.steps.at(-1)&&t<(s.start_ms+(s.elapsed_ms||1e9));
   if(ended){node('span',OUTCOME[v.outcome]||v.outcome,now,'tag '+v.outcome);node('b',' after '+v.steps.length+(v.steps.length===1?' step':' steps')+', '+secs(v.end_ms-v.start_ms),now).style.display='inline';if(v.reason)node('span',v.reason,now,'said');}
   else{node('b',(going&&s.status!=='thinking'?'Reading the page':did(s)),now);}
   if(s.say&&(ended||!going))node('span','“'+s.say+'”',now,'said');}}

 // Lanes: every step of every visitor on one clock.
 const lanes=node('div','',wb,'lanes'),dots=[];
 for(const v of vs){const l=node('div','',lanes,'lane');node('span',v.name,l);const tr=node('div','',l,'track');
  if(v.steps.length){const bar=node('div','',tr,'bar');bar.style.left=(v.start_ms/total*100)+'%';bar.style.width=(((v.end_ms??total)-v.start_ms)/total*100)+'%';}
  for(const s of v.steps){const d=node('button','',tr,'dot s-'+s.status+(s.claim&&s.status!=='got_there'?' s-claim':''));d.type='button';d.style.left=(s.start_ms/total*100)+'%';d.title=v.name+', step '+s.order+': '+did(s);d.setAttribute('aria-label',d.title);d.onclick=()=>focus(v,s,d);dots.push({d,s});}
  const end=node('span','',l,'end');if(v.outcome&&v.status==='complete')node('span',OUTCOME[v.outcome],end,'tag '+v.outcome);}
 const ax=node('div','',lanes,'axis');node('span','',ax);const sc2=node('div','',ax);node('span','0s',sc2);node('span',live?'so far':secs(total)+' real time',sc2);node('span','',ax,'pad');
 const head=node('div','',lanes,'playhead');
 const ctl=node('div','',wb,'controls');
 const lg=node('div','',ctl,'legend');for(const [cls,t] of [['s-got_there','job completed'],['s-claim','said done, not accepted'],['s-stuck','stuck'],['s-error_page','hit an error or a closed door'],['','a normal step'],['s-left_app','left the app']]){const s=node('span','',lg);const i=node('i','',s,'dot '+cls);i.style.position='static';i.style.margin='0 4px 0 0';s.append(t);}
 const fo=node('div','',wb,'focus');fo.hidden=true;
 function focus(v,s,d){for(const x of dots)x.d.classList.toggle('on',x.d===d);fo.hidden=false;fo.replaceChildren();const fig=node('figure','',fo);const img=node('img','',fig,'shot'+(v.phone?' tall':''));img.alt='Saved screen for this step';photo(r.id,s.screenshot,img);const tx=node('div','',fo);node('p',v.name+' · step '+s.order+' of up to '+v.max_steps+' · '+secs(s.elapsed_ms||0),tx,'eyebrow');node('h3',did(s),tx);if(s.say)node('p','“'+s.say+'”',tx);
  if(s.claim){node('p','Said the job was done here, pointing at: “'+s.claim.quote.replace(/\s+/g,' ').slice(0,200)+'”',tx);node('p','Second check of this screen and the steps so far: '+(s.claim.confirmed?'agreed.':'did not agree.')+' '+(s.claim.why||''),tx);if(s.claim_state?.state==='screen_confirmed')node('p','Not counted as completed. The task has more parts: still to '+s.claim_state.missing.map(m=>({went_somewhere:'open something beyond the first screen',came_back:'come back to an earlier screen'}[m])).join(' and ')+'.',tx,'hint');}
  if(s.wish)node('p','Asked for: '+s.wish,tx);if(s.reason)node('p',s.reason,tx,'hint');node('p',short(s.url),tx,'hint');node('p',s.page_text,tx,'words');}
 if(live){paint(Infinity);return;}
 paint(Infinity);
 const play=node('button','Play '+(tries.length>1?'try '+(sel+1):'the run')+' in real time →',ctl,'quiet');play.type='button';
 play.onclick=()=>{clearInterval(playTimer);const t0=performance.now();head.style.display='block';play.disabled=true;const track=lanes.querySelector('.track');
  playTimer=setInterval(()=>{const t=performance.now()-t0;for(const x of dots)x.d.classList.toggle('future',x.s.start_ms>t);paint(t);const box=track.getBoundingClientRect(),lb=lanes.getBoundingClientRect();head.style.left=(box.left-lb.left+Math.min(1,t/total)*box.width)+'px';
   if(t>=total+400){clearInterval(playTimer);head.style.display='none';play.disabled=false;play.textContent='Play it again →';paint(Infinity);}},80);};

 // Findings, only from what a visitor hit, and only when it happened in two of three tries.
 const fx=node('div','',card,'block');node('h3','What to fix, from what they hit',fx);
 if(!(r.findings||[]).length)node('p',r.fixes_note||'',fx);
 else{node('p',(n>1?'A finding is shown only when the same visitor hit it in at least 2 of '+n+' tries. ':'One try only, so each finding was seen once. ')+'Each one is tied to a step and a saved screen. The words are the test visitor’s, and a test visitor is a model, not a person.',fx,'hint');
  for(const f of r.findings){const row=node('div','',fx,'fix');const fig=node('figure','',row);const e=f.kind==='different_places'?f.evidence.at(-1):f.evidence[0];const img=node('img','',fig,'shot'+(sum.find(v=>v.id===e.visitor)?.phone?' tall':''));img.alt='Saved screen for this finding';photo(r.id,e.screenshot,img);node('figcaption',short(f.page),fig);
   const tx=node('div','',row);node('h4',f.title,tx);node('span','What happened',tx,'k');node('p',f.what_happened,tx);
   node('span','Who, and how often',tx,'k');node('p',f.evidence.map(x=>x.name+(n>1?', try '+x.try:'')+', step '+x.step).join(' · ')+(n>1?'. Seen in '+f.hits+' of '+f.tries+' tries.':'.'),tx);
   for(const x of f.evidence.slice(0,3))if(x.said){node('span',x.name+(n>1?', try '+x.try:'')+' said',tx,'k');node('p','“'+x.said+'”',tx);}
   if(f.page_text){node('span','Words on that page',tx,'k');node('blockquote',f.page_text.slice(0,240),tx);}}}
 if((r.set_aside||[]).length){node('h3','Set aside: possibly caused by the test rig',fx).style.marginTop='18px';node('p','In these visits the rig refused a request the app made, because it was not a plain read. A stop there may be our doing, so it is not offered as a fix.',fx,'hint');for(const f of r.set_aside){node('p','“'+f.title+'” · '+short(f.page),fx);node('p',f.what_happened,fx,'hint');}}
 if(r.seen_once)node('p',r.seen_once+(r.seen_once===1?' more stop happened in one try only and is':' more stops happened in one try only and are')+' not shown as a finding. Open the tries above to see them.',fx,'hint');

 // Graphs from this try only.
 if(vs.some(v=>v.steps.length)){const gr=node('div','',card,'block');node('h3',(tries.length>1?'Try '+(sel+1):'The run')+' in numbers',gr);const ch=node('div','',gr,'charts');
  const colour=v=>({got_there:'var(--good)',stuck:'var(--bad)',left_app:'var(--left)'}[v.outcome]||'var(--wait)');const nm=v=>v.name.replace('In a hurry, on a phone','On a phone');
  let c1=chart(ch,'Steps each visitor took','Fewer steps to the job is better. Colour shows how it ended.');const maxS=Math.max(...vs.map(v=>v.max_steps));
  let s1=svg('svg',{viewBox:'0 0 320 '+(vs.length*26+6),role:'img','aria-label':'Steps taken by each test visitor'},c1);
  vs.forEach((v,i)=>{svg('text',{x:0,y:i*26+16},s1,nm(v));svg('rect',{x:128,y:i*26+5,width:160,height:14,fill:'var(--line)',opacity:.45},s1);svg('rect',{x:128,y:i*26+5,width:160*v.steps.length/maxS,height:14,fill:colour(v),class:'grow'},s1);svg('text',{x:294,y:i*26+16},s1,v.steps.length);});
  c1=chart(ch,'Time until the job was completed','Seconds from opening the app to the confirmed screen.');const maxT=Math.max(1,...vs.map(v=>v.time_to_goal_ms||0));
  s1=svg('svg',{viewBox:'0 0 320 '+(vs.length*26+6),role:'img','aria-label':'Time to completed job for each test visitor'},c1);
  vs.forEach((v,i)=>{svg('text',{x:0,y:i*26+16},s1,nm(v));if(v.time_to_goal_ms!=null){const w=Math.max(3,150*v.time_to_goal_ms/maxT);svg('rect',{x:128,y:i*26+5,width:w,height:14,fill:'var(--good)',class:'grow'},s1);svg('text',{x:134+w,y:i*26+16},s1,secs(v.time_to_goal_ms));}else svg('text',{x:128,y:i*26+16,class:'m'},s1,v.outcome==='left_app'?'left the app':'never completed it');});
  c1=chart(ch,'Where they dropped','Visitors still trying after each step. The line falls when one completes the job, gets stuck or leaves.');
  const W=320,H=132,x0=22,x1=310,y0=106,y1=10,m=vs.length;s1=svg('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'Visitors still trying after each step'},c1);
  const X=k=>x0+(x1-x0)*k/maxS,Y=q=>y0-(y0-y1)*q/m;for(let q=0;q<=m;q++){svg('line',{x1:x0,x2:x1,y1:Y(q),y2:Y(q),stroke:'var(--line)','stroke-width':q?0.5:1},s1);svg('text',{x:4,y:Y(q)+4,class:'m'},s1,q);}
  let path='M'+X(0)+' '+Y(m),alive=m;for(let k=1;k<=maxS;k++){path+=' H'+X(k);const out=vs.filter(v=>v.steps.length===k);alive-=out.length;if(out.length)path+=' V'+Y(alive);out.forEach((v,j)=>svg('circle',{cx:X(k),cy:Y(alive+j+0.5),r:4.5,fill:colour(v)},s1).append(svg('title',{},null,v.name+': '+OUTCOME[v.outcome])));svg('text',{x:X(k)-3,y:H-10,class:'m'},s1,k);}
  svg('path',{d:path,fill:'none',stroke:'var(--ink)','stroke-width':2},s1);svg('text',{x:x1-52,y:H-0.5,class:'m'},s1,'step');}

 if((r.baseline||[]).length){const b=node('div','',card,'block');node('h3','Basic checks, no model',b);node('p','Plain yes or no checks on the first page. They say nothing about whether a person can use the app.',b,'hint');const ck=node('div','',b,'checks');for(const x of r.baseline){const row=node('div','',ck,'check');node('span',x.label,row);node('b',x.status==='passed'?'Yes':'No',row,x.status);node('span',x.detail,row);}}
 const lim=node('div','',card,'block limits');for(const l of r.limitations||[])node('p',l,lim);if(r.replayed)node('p','This is a saved run from '+new Date(r.finished_at).toLocaleString()+', for this exact task and setup. Opening it made no model call.',lim);}
function chart(parent,title,sub){const c=node('div','',parent,'chart');node('h4',title,c);node('p',sub,c);return c;}
const lower=s=>s?s[0].toLowerCase()+s.slice(1):'';
const short=u=>(u||'').replace(/^https?:\/\//,'').slice(0,70);

function showBasic(r,card){node('p',r.name,card,'eyebrow');node('h2',r.status!=='complete'?'Opening your app':r.target==='repo'?'That is a code link, not a running app':'Basic check done',card,'verdict');
 if(r.status!=='complete'){node('p',r.steps.at(-1)?.label||'Opening the first page',card);return;}
 node('p',r.fixes_note||'A basic check has no test visitors. Start a full run to see where a person gets stuck.',card);
 const b=node('div','',card,'block');node('h3','Basic checks, no model',b);const ck=node('div','',b,'checks');for(const c of r.checks||[]){const row=node('div','',ck,'check');node('span',c.label,row);node('b',{passed:'Yes',failed:'No',not_run:'Not checked'}[c.status],row,c.status);node('span',c.reason||'',row);}
 if(r.steps?.length){const rp=node('div','',card,'block');node('h3','Saved screens',rp);const img=node('img','',rp,'shot');img.alt='A saved screen from the check';const cap=node('p','',rp,'hint');const bs=node('div','',rp,'steps-old');const pick=i=>{const s=r.steps[i];cap.textContent=(i+1)+' of '+r.steps.length+' · '+s.label+' · '+secs(s.elapsed_ms);[...bs.children].forEach((x,j)=>x.classList.toggle('active',j===i));photo(r.id,s.screenshot,img);};r.steps.forEach((s,i)=>{const x=node('button',(i+1)+' · '+s.label,bs);x.type='button';x.onclick=()=>pick(i);});pick(0);}
 const lim=node('div','',card,'block limits');for(const l of r.limitations||[])node('p',l,lim);}

const mode=()=>$('#depth').value==='quick'?'quick':'swarm',tryCount=()=>$('#depth').value==='full3'?3:1;
async function refresh(){const d=await api('results');all=d.runs;const ex=$('#examples');if(ex.children.length<2){for(const t of Object.values(d.targets).filter(t=>t.url.startsWith('https://'))){const b=node('button',t.name,ex);b.type='button';b.onclick=()=>{$('#app-url').value=t.url;};}const b=node('button','A broken app we planted',ex);b.type='button';b.onclick=()=>{$('#app-url').value=location.origin+'/control/';};}
 const hb=$('#history');hb.replaceChildren();node('h3','Saved runs',hb);const latest=new Map();for(const r of all){if(r.superseded||(r.mode==='swarm'&&!r.tries))continue;const k=r.mode+'|'+r.url.replace(/\/$/,'')+'|'+(r.job?.text||'')+'|'+(r.tries_planned||'');if(!latest.has(k))latest.set(k,r);}
 if(!latest.size)node('p','None yet.',hb,'hint');
 for(const r of latest.values()){const b=node('button','',hb,current?.id===r.id?'selected':'');b.dataset.id=r.id;node('strong',r.name,b);if(r.job?.text)node('span',r.job.text+' · '+(r.tries_planned===3?'3 tries':'1 try'),b,'job');node('span',r.mode==='swarm'?(r.headline||'Running now'):'Basic check',b);b.onclick=()=>show(r);}return d;}
async function poll(id){clearTimeout(timer);const r=await api('result/'+id);show(r);if(r.status!=='complete')timer=setTimeout(()=>poll(id).catch(e=>{$('#message').textContent=e.message;}),700);else{await refresh();$('#message').textContent='Your run is ready.';$('#try').disabled=false;}}
async function begin(body){$('#try').disabled=true;$('#message').textContent='Opening your app.';try{const r=await api('start',body);if(r.replayed){show(r);await refresh();$('#message').textContent='This exact task was already run on this address. This is the saved result, at no cost.';$('#try').disabled=false;}else{current=null;show(r);await poll(r.id);}}catch(err){$('#message').textContent=err.message;$('#try').disabled=false;}}
function askJob(found,url){clearInterval(playTimer);current=null;const box=$('#result');box.replaceChildren();const card=node('article','',box,'result jobcard');node('p','Before we start',card,'eyebrow');node('h2','We think people come here to:',card,'verdict');
 const input=node('input','',card);input.id='job';input.value=found.text||'';input.maxLength=200;input.setAttribute('aria-label','What people come to this app to do');input.placeholder='Say in one short line what people come to do';
 node('p',found.text?(found.source==='fixed'?'Fixed for the planted app. ':'We read '+found.pages_read.length+(found.pages_read.length===1?' page':' pages')+' of your app and asked the NVIDIA model. ')+'This line is a guess by the model. Check it, and change it if it is wrong. If you leave it as it is, the result will say the task was not checked by you. Four test visitors will try exactly this. One sceptic keeps its own question.':'We could not read a task from your pages. Write it yourself.',card);
 if(found.note)node('p',found.note,card).style.fontWeight='700';
 if(found.what)node('p','What we read: '+found.what,card,'hint');
 if(found.needs_write)node('p','This task needs an account or saves something. Test visitors only read. They can show how far a person gets before that door. They cannot complete it, and the result will say so.',card,'hint');
 const go=node('button','Start the run →',card,'primary');go.type='button';go.onclick=()=>{if(!input.value.trim()){input.focus();return;}begin({url,mode:'swarm',job:input.value,tries:tryCount(),own_machine:$('#own').checked,fresh:$('#fresh').checked});};
 input.onkeydown=e=>{if(e.key==='Enter')go.click();};
 if((found.saved||[]).length){const sv=node('div','',card,'block');node('h3','Saved results for this address',sv);node('p','A saved result is reused only for the same task, the same number of tries and the same setup. A different task runs fresh.',sv,'hint');for(const x of found.saved){const b=node('button','“'+(x.job||'older run, no task line')+'” · '+(x.tries===3?'3 tries':'1 try')+' · '+(x.headline||''),sv,'quiet');b.type='button';b.style.display='block';b.style.margin='6px 0';b.onclick=()=>{const r=all.find(r=>r.id===x.id);if(r)show(r);};}}
 input.focus();input.select();}
$('#drop-form').onsubmit=async e=>{e.preventDefault();const url=$('#app-url').value;if(mode()==='quick')return begin({url,mode:'quick'});$('#try').disabled=true;$('#message').textContent='Reading your pages to see what people come here to do.';try{const found=await api('job',{url,own_machine:$('#own').checked});$('#message').textContent='';askJob(found,url);}catch(err){$('#message').textContent=err.message;}finally{$('#try').disabled=false;}};
if(token)refresh().then(d=>{const id=new URLSearchParams(location.search).get('visit');const r=d.runs.find(r=>r.id===id);if(r)show(r);}).catch(e=>{$('#message').textContent=e.message;});
else $('#message').textContent='Open the private link printed by your local session to start.';
