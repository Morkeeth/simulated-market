'use strict';
const $=s=>document.querySelector(s), form=$('#form');
let token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem('workspace-token')||'';
if(token){sessionStorage.setItem('workspace-token',token);history.replaceState(null,'',location.pathname);}
let current=null, saved=[], decisionRows=[], allowAgents=false, allowSponsor=false, readiness=null, tokenFactoryReadiness=null, selectedJob=null, timer=null, dirty=false, inspectedFrame=null, preparing=false, viewVersion=0;
async function api(path,body){const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'X-Workspace-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}
function error(e){$('#error').textContent=e.message;$('#error').scrollIntoView({block:'center',behavior:'smooth'});}
function clear(){ $('#error').textContent='';$('#notice').textContent=''; }
function node(tag,text,parent){const e=document.createElement(tag);e.textContent=text;parent.append(e);return e;}
function details(title,text,parent){const d=document.createElement('details');node('summary',title,d);node('pre',text,d);parent.append(d);}
function fields(){const f=Object.fromEntries(new FormData(form));for(const k of ['n','agents','seed'])f[k]=Number(f[k]);return f;}
function body(){return {id:current?.id,revision:current?.revision||0,form:fields()};}
function paidBackend(backend){return backend==='sponsor'||backend==='tokenfactory-local';}
function runtime(){
 const backend=form.elements.backend.value,paid=paidBackend(backend),hybrid=backend==='tokenfactory-local';
 $('#backend-label').textContent=paid?(hybrid?'SIMULATED · LOCAL Docker · hosted model selected, no execution yet':'SIMULATED · sponsor selected, no execution yet'):'SIMULATED · LOCAL';
 const check=hybrid?tokenFactoryReadiness:readiness;
 $('#runtime').textContent=paid?((hybrid?'Token Factory model-directed readers and optional mini-swe-agent participants in cached local Docker. ':'Token Factory model-directed readers and optional mini-swe-agent participants in Nebius. ')+(allowSponsor?'Explicit preview confirmation is required. ':'Execution is off; authorized service startup with --allow-sponsor is required. ')+(check?.missing?.length?'Prerequisites: '+check.missing.join(' '):'Configured prerequisites present; service access remains to be checked.')):('Cached Docker, no network or host mounts. '+(allowAgents?'Local coding agents authorized; cached runtime required.':'Local coding agents require service startup with --allow-agents.'));
}
function mode(){runtime(); $('#files').hidden=form.elements.mode.value!=='files';$('#git').hidden=form.elements.mode.value!=='git'; }
function stop(){viewVersion++;clearTimeout(timer);selectedJob=null;inspectedFrame=null;$('#trial').hidden=true;$('#decision').hidden=true;trialData=null;}
const choiceName={base:'Keep current',head:'Ship proposed',defer:'Test with people'};
function initialChoice(){return decisionRows.find(r=>r.stage==='initial'&&r.snapshot===current?.preview?.id);}
function renderInitial(){
 const chosen=initialChoice();
 $('#initial-form').hidden=!!chosen;
 $('#initial-saved').textContent=chosen?'Frozen before execution: '+choiceName[chosen.choice]+'. '+chosen.reason:'Save your initial choice to start this comparison.';
 $('#start').disabled=!current?.preview||dirty||preparing||!chosen||current.runs.some(r=>r.snapshot===current.preview.id);
}
async function loadDecisions(id){
 const response=await api('decisions/'+id);
 if(current?.id!==id)return;
 decisionRows=response.decisions;
 renderInitial();
 if(selectedJob&&!$('#decision').hidden)renderReviewed();
}
function renderReviewed(){
 const run=current?.runs.find(r=>r.id===selectedJob);
 const initial=decisionRows.find(r=>r.stage==='initial'&&r.snapshot===run?.snapshot);
 $('#decision-before').textContent=initial?'Before the run: '+choiceName[initial.choice]+'. '+initial.reason:'No initial choice is bound to this run.';
 const history=$('#decision-history');history.replaceChildren();
 const reviewed=decisionRows.filter(r=>r.stage==='reviewed'&&r.job===selectedJob);
 if(reviewed.length)node('h3','Saved choices',history);
 for(const row of reviewed){
  const p=node('p',choiceName[row.choice]+': '+row.reason,history);
  p.className='small';
  node('p',row.choice===initial?.choice?'Choice stayed the same.':'Choice changed after seeing the simulation.',history).className='small';
 }
 node('p','A changed choice is observable here. Better decisions require later independent user outcomes and a fair comparison.',history).className='small';
}
$('#initial-form').onsubmit=async e=>{
 e.preventDefault();clear();
 try{if(!current?.preview||dirty||preparing)throw Error('Prepare the exact inputs first.');
  const f=Object.fromEntries(new FormData(e.currentTarget));
  decisionRows=(await api('decision',{id:current.id,stage:'initial',snapshot:current.preview.id,expected:current.preview.expected,...f})).decisions;
  renderInitial();
 }catch(err){error(err);}
};
$('#reviewed-form').onsubmit=async e=>{
 e.preventDefault();clear();
 const reviewedForm=e.currentTarget;
 try{if(!selectedJob||!current)throw Error('Open a completed comparison first.');
  const f=Object.fromEntries(new FormData(reviewedForm));
  decisionRows=(await api('decision',{id:current.id,stage:'reviewed',job:selectedJob,...f})).decisions;
  reviewedForm.elements.reason.value='';renderReviewed();
 }catch(err){error(err);}
};
async function refresh(){const d=await api('drafts');saved=d.drafts;allowAgents=d.allowAgents;allowSponsor=d.allowSponsor;readiness=d.sponsorReadiness;tokenFactoryReadiness=d.tokenFactoryReadiness;$('#storage').textContent='Private storage: '+d.root;runtime();const box=$('#saved');box.replaceChildren();if(!saved.length)node('p','No saved comparisons yet. Choose your project below.',box);for(const s of saved){const b=node('button',s.form.title+' · '+s.runs.length+' saved run'+(s.runs.length===1?'':'s'),box);b.onclick=()=>open(s);}}
function showPreview(){const p=current?.preview;$('#start').disabled=true;$('#preview').hidden=!p||dirty||preparing;if(!p||preparing)return;const box=$('#preview-body');box.replaceChildren();node('h3',p.contract.name,box);node('p',p.contract.goal,box);const sponsor=paidBackend(p.config.backend),hybrid=p.config.backend==='tokenfactory-local';node('p',p.config.n+(sponsor?' model-directed readers; ':' scripted readers; ')+p.config.agents+(sponsor?' sponsor coding agent':' local coding agent')+(p.config.agents===1?'':'s')+(p.config.agents===0?' (not run)':'')+'; seed '+p.config.seed+'. Base, identical-input control, then proposed instructions.',box);node('p',sponsor?'Sponsor model: '+p.config.sponsor.model+(hybrid?' · LOCAL Docker image: '+p.contract.image_id:' · Nebius image: '+p.config.sponsor.image)+' · cost unknown':'Runtime: cached '+p.contract.image+' · network none · no downloads',box);details('Comparison code and Python runtime',JSON.stringify(p.engine,null,2),box);details('Exact source commit and allowed files',JSON.stringify(p.contract.source,null,2),box);details('Frozen base image identity',p.contract.image_id,box);details('Setup commands inside the sandbox',JSON.stringify(p.contract.setup,null,2),box);details('Success checks in evaluation order',JSON.stringify(p.contract.steps,null,2),box);for(const name of ['base','head'])details((name==='base'?'Current':'Proposed')+' complete instructions · '+p.sources[name].sha256,p.documents[name],box);details('Exact document provenance',JSON.stringify(p.sources,null,2),box);node('p','The final installed checkpoint is frozen once at start and recorded in every run. The evaluator defines success; another correct approach may fail a narrow check.',box);$('#sponsor-consent').hidden=!sponsor;$('#sponsor-transfer').textContent=hybrid?'Documentation, task and agent command output go to Token Factory. Command output may expose source. Source archives, setup and evaluator stay in local Docker and are not uploaded to Nebius. Hosted cost is unknown.':'Source files, setup commands and evaluators go to Nebius. Documentation and command history go to Token Factory. Optional Tavily receives the project name only when explicitly enabled. Hosted cost is unknown and remote snapshots may persist.';$('#consent').checked=false;renderInitial();}
function showHistory(){const runs=current?.runs||[];$('#history').hidden=!runs.length;$('#runs').replaceChildren();for(const r of runs){const b=node('button','Open saved run '+r.id.slice(0,8),$('#runs'));b.onclick=()=>watch(r.id);}}
function open(s){stop();clear();current=s;decisionRows=[];dirty=false;form.elements.backend.value=s.form.backend||'local';for(const [key,value]of Object.entries(s.form))form.elements[key].value=value;mode();showPreview();showHistory();$('#run').hidden=true;$('#result').hidden=true;$('#notice').textContent='Private draft restored. Frozen preview and earlier runs are retained.';loadDecisions(s.id).catch(error);}
form.addEventListener('input',()=>{dirty=true;$('#preview').hidden=true;$('#result').hidden=true;$('#notice').textContent='Unsaved changes. Preview again before starting.';mode();});
$('#new').onclick=()=>{stop();current=null;decisionRows=[];dirty=false;form.reset();mode();clear();for(const id of ['preview','run','history','result'])$('#'+id).hidden=true;form.elements.title.focus();};
$('#save').onclick=async()=>{if(preparing)return;clear();try{current=await api('save',body());dirty=false;showPreview();showHistory();await refresh();await loadDecisions(current.id);$('#notice').textContent='Draft saved privately on this machine.';}catch(e){error(e);}};
form.onsubmit=async e=>{
 e.preventDefault();if(preparing)return;clear();
 const requested=body(),view=viewVersion;
 preparing=true;dirty=true;showPreview();$('#prepare').disabled=true;$('#save').disabled=true;
 $('#notice').textContent='Preparing a new frozen preview. Start is unavailable until it is ready.';
 try{
  const next=await api('preview',requested);
  if(view!==viewVersion)return;
  current=next;dirty=JSON.stringify(fields())!==JSON.stringify(requested.form);
  await refresh();if(view!==viewVersion)return;
  await loadDecisions(current.id);if(view!==viewVersion)return;
  $('#notice').textContent=dirty?'Inputs changed while preparing. Preview again before starting.':'Exact inputs frozen. Review them before starting.';
 }catch(e){
  if(view===viewVersion){dirty=true;error(e);await refresh();if(view===viewVersion&&current)current=saved.find(s=>s.id===current.id)||current;}
 }finally{
  preparing=false;$('#prepare').disabled=false;$('#save').disabled=false;showPreview();showHistory();
  if(view===viewVersion&&!dirty&&current?.preview)$('#preview').scrollIntoView({behavior:'smooth'});
 }
};
$('#start').onclick=async()=>{if(preparing||dirty||!current?.preview||!initialChoice())return;clear();$('#start').disabled=true;try{const j=await api('start',{id:current.id,revision:current.revision,expected:current.preview.expected,...(paidBackend(current.preview.config.backend)&&$('#consent').checked?{sponsorConsent:current.preview.expected}:{})});await refresh();current=saved.find(s=>s.id===current.id);showHistory();await watch(j.id);}catch(e){error(e);showPreview();}};
async function watch(id){stop();selectedJob=id;$('#status').textContent='Checking this saved run';$('#log').textContent='';$('#run-error').textContent='';$('#inspect').hidden=true;$('#human-trial').hidden=true;$('#run').hidden=false;$('#result').hidden=true;await poll(id);}
async function poll(id){try{const j=await api('job/'+id);if(selectedJob!==id)return;$('#status').textContent=({starting:'Starting the reviewed comparison',running:'Running the reviewed comparison',complete:'Complete · identical-input control passed',failed:'Run failed · no completed comparison',unconfirmed:'Run state unconfirmed · new runs held',interrupted:'Run interrupted · no completion claimed'})[j.state]||j.state;$('#run-error').textContent=j.error||'';$('#log').textContent=j.log||'Waiting for the engine to start.';$('#output').textContent='Preserved output: '+j.output;$('#inspect').hidden=j.state!=='complete';$('#human-trial').hidden=j.state!=='complete';if(['starting','running','unconfirmed'].includes(j.state))timer=setTimeout(()=>poll(id),600);}catch(e){error(e);}}
$('#inspect').onclick=async()=>{try{const id=selectedJob,[result,cohort]=await Promise.all([api('result/'+id),api('trial/'+id)]);if(id!==selectedJob)return;const frame=$('iframe'),context={jobId:id,nonce:crypto.randomUUID()};inspectedFrame=context;frame.onload=()=>{if(inspectedFrame!==context||selectedJob!==id)return;frame.contentWindow.postMessage({type:'local-comparison',files:result,context,trial:trialSummary(cohort)},location.origin);};frame.src='/';$('#result').hidden=false;$('#decision').hidden=false;await loadDecisions(current.id);renderReviewed();$('#result').scrollIntoView({behavior:'smooth'});}catch(e){error(e);}};
window.addEventListener('message',e=>{const c=inspectedFrame;if(e.origin!==location.origin||e.source!==$('iframe').contentWindow||!c||!e.data||e.data.type!=='open-human-trial'||e.data.jobId!==c.jobId||e.data.nonce!==c.nonce||selectedJob!==c.jobId)return;openTrial(c.jobId);});
$('#revise').onclick=()=>{stop();$('#run').hidden=true;$('#result').hidden=true;$('#notice').textContent='Change the proposed document or revision, then preview again. Earlier runs stay saved.';form.elements.head_doc.focus();form.scrollIntoView({behavior:'smooth'});};
refresh().catch(error);mode();

// A human cohort stays private and separate from the simulated run files.
let trialData=null;
function trialInput(parent,label,name,value='',type='text'){
 const l=node('label',label,parent), e=document.createElement('input');e.name=name;e.type=type;e.value=value;l.append(e);return e;
}
function trialButton(parent,label,action){const b=node('button',label,parent);b.type='button';b.onclick=async()=>{b.disabled=true;clear();try{await action();}catch(e){error(e);}finally{b.disabled=false;}};return b;}
async function trialAction(action,body){const id=selectedJob;const d=await api('trial/'+action,{id,...body});if(id===selectedJob){trialData=d;renderTrial();syncTrial(d);}}
async function openTrial(id){clear();try{const d=await api('trial/'+id);if(id!==selectedJob)return;trialData=d;renderTrial();syncTrial(d);$('#trial').scrollIntoView({behavior:'smooth'});}catch(e){error(e);}}
$('#human-trial').onclick=()=>openTrial(selectedJob);
function renderTrial(){
 const box=$('#trial-body');box.replaceChildren();$('#trial').hidden=false;
 node('p','Keep the same task, starting environment and time limit. Assign the next consenting person the next slot before they see either document. Use one distinct consenting person per slot. Never reuse a person in either arm; each person tries one version once. Do not coach them or reveal the simulated prediction.',box);
 node('p','This records what you report. Anonymous slots cannot detect repeated people or verify consent, participant identity or the session. Use anonymous slot IDs and avoid personal details. Nothing is sent or run.',box).className='small';
 if(!trialData.trial){
  const f=document.createElement('form');box.append(f);
  const count=trialInput(f,'Total people to invite (even number, split equally)','participants','6','number');count.min=2;count.max=200;count.step=2;
  const time=trialInput(f,'Same time limit per person, in minutes','minutes','15','number');time.min=1;time.max=240;
  trialInput(f,'Who qualifies, and how will you recruit them?','recruitment');
  trialInput(f,'How will each session start from the same prepared environment?','environment');
  node('p','Freeze these details before collecting observations. The plan uses the exact completed comparison and preserves its goal and success checks. Creating it does not recruit or contact anyone.',f).className='small';
  const submit=node('button','Freeze the human trial plan',f);submit.className='primary';submit.type='submit';
  f.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const data=Object.fromEntries(new FormData(f));data.participants=Number(data.participants);data.minutes=Number(data.minutes);await trialAction('create',data);}catch(e){error(e);}finally{submit.disabled=false;}};
  return;
 }
 const t=trialData.trial,p=t.plan,closed=t.state==='closed';
 node('h3',closed?'Cohort closed · observations preserved':'Plan frozen · collect each session',box);
 node('p',p.goal,box);node('p','Time limit: '+p.minutes+' minutes per person. '+p.recruitment,box);
 details('Identical starting environment',p.environment,box);
 details('Frozen source, setup and success checks',JSON.stringify({source:p.source,image:p.image_id,setup:p.setup,checks:p.checks},null,2),box);
 details('Exact comparison and document identities',JSON.stringify({completed_result:p.result_sha256,documents:p.documents},null,2),box);
 const tally=node('div','',box);tally.className='grid';
 for(const arm of ['base','head']){const total=trialData.totals[arm],card=node('article','',tally);node('h3',arm==='base'?'Current instructions':'Proposed instructions',card);node('p',total.reached+' of '+total.n+' reported sessions reached the goal',card);node('p',total.pending+' pending · '+total.withdrawn+' withdrew',card).className='small';}
 node('p',closed?trialData.limits:'The comparison with the prediction appears after every slot is accounted for and you close the cohort. A pending slot is never counted as a failure.',box).className='small';
 for(const slot of p.participants){
  const o=t.observations[slot.id],d=document.createElement('details');box.append(d);
  node('summary',slot.id+' · '+(slot.arm==='base'?'current':'proposed')+' · '+(o?o.outcome.replaceAll('_',' '):'not recorded'),d);
  details('Session card: task and assigned instructions only',p.goal+'\n\nTime limit: '+p.minutes+' minutes. Try these instructions without coaching.\n\n'+trialData.documents[slot.arm],d);
  if(o)node('p','Reported observation: '+o.evidence,d);
  if(closed)continue;
  const f=document.createElement('form');d.append(f);
  const l=node('label','Outcome',f),sel=document.createElement('select');sel.name='outcome';l.append(sel);
  for(const [v,txt] of [['not_reached','Did not reach the frozen goal'],['reached','Reached the frozen goal'],['withdrawn','Withdrew or could not attend']]){const op=node('option',txt,sel);op.value=v;}if(o)sel.value=o.outcome;
  trialInput(f,'What did you observe? Include success-check evidence, help given, or reason for withdrawal.','evidence',o?.evidence||'');
  if(o)trialInput(f,'Why are you correcting this observation? The earlier entry stays in history.','correction');
  const label=node('label','',f),consent=document.createElement('input');consent.type='checkbox';consent.name='consent';consent.style='display:inline;width:auto';label.append(consent,document.createTextNode(' The person consented to this record. No personal details are included.'));
  const b=node('button',o?'Save correction':'Save observed outcome',f);b.type='submit';
  f.onsubmit=async e=>{e.preventDefault();b.disabled=true;try{await trialAction('record',{...Object.fromEntries(new FormData(f)),participant:slot.id,consent:consent.checked,revision:t.revision});}catch(e){error(e);}finally{b.disabled=false;}};
 }
 if(closed){
  node('h3','Prediction compared with reported outcomes',box);
  node('p','Prediction: '+trialData.prediction.direction+' · '+trialData.prediction.labels.join(' · '),box);
  node('p','Observed direction: '+trialData.score.rows[0].observed+'. Calibration: '+trialData.score.verdict+'. Magnitude: UNCALIBRATED.',box);
  node('p','All participants together count as one outcome row. One trial cannot establish that the simulator predicts people accurately.',box);
  details('Canonical calibration score',JSON.stringify(trialData.score,null,2),box);
  trialButton(box,'Save outcome row to a local file',async()=>{const blob=new Blob([JSON.stringify(trialData.outcome_row)+'\n'],{type:'application/x-ndjson'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='human-trial-'+p.id+'.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 }else{
  node('p','Closing preserves this cohort and its correction history. Complete or mark every slot withdrawn first; each document must have at least one observed session.',box).className='small';
  trialButton(box,'Close cohort and compare with prediction',()=>trialAction('close',{revision:t.revision}));
 }
 if(t.history.length)details('Observation and correction history',JSON.stringify(t.history,null,2),box);
}

function trialSummary(d){return d.trial?{state:d.trial.state,totals:d.totals,observed:d.score.rows[0]?.observed||null,verdict:d.score.verdict,cohortRows:d.score.n,recruitment:d.trial.plan.recruitment}:{state:'none'};}
function syncTrial(d){const c=inspectedFrame;if(!c||c.jobId!==selectedJob)return;$('iframe').contentWindow.postMessage({type:'workspace-trial-state',context:c,trial:trialSummary(d)},location.origin);}
const setupForm=$('#setup-form');let setupSource=null;
$('#setup-toggle').onclick=()=>{setupForm.hidden=!setupForm.hidden;};
$('#setup-example').onclick=()=>{setupForm.hidden=false;setupForm.elements.name.value='Pocket totals example';setupForm.elements.goal.value='Run total.py and save the sum 7 in total.txt.';setupForm.elements.check_title.value='Saved the correct total';setupForm.elements.probe.value='test "$(cat total.txt 2>/dev/null)" = 7';$('#setup-example-note').textContent='Example values only. Choose your own committed project and files, and change the task/check to match it. No file was created and nothing ran.';};
setupForm.addEventListener('input',e=>{if(['repo','ref'].includes(e.target.name)){setupSource=null;$('#setup-files').replaceChildren();$('#setup-commit').textContent='Source changed. Read the file list again before saving.';}});
$('#setup-source').onclick=async()=>{clear();const repo=setupForm.elements.repo.value,ref=setupForm.elements.ref.value;try{const d=await api('source',{repo,ref});if(repo!==setupForm.elements.repo.value||ref!==setupForm.elements.ref.value)return;setupSource=d;$('#setup-commit').textContent='Frozen source revision: '+d.commit;const box=$('#setup-files');box.replaceChildren();node('p','Select only source files needed for this task. No file is selected automatically.',box);for(const name of d.files){const l=node('label','',box),e=document.createElement('input');e.type='checkbox';e.name='source_file';e.value=name;e.style='display:inline;width:auto';l.append(e,document.createTextNode(' '+name));}}catch(e){error(e);}};
setupForm.onsubmit=async e=>{e.preventDefault();clear();try{if(!setupSource)throw Error('Read the committed file list first.');const f=Object.fromEntries(new FormData(setupForm)),files=[...setupForm.querySelectorAll('[name=source_file]:checked')].map(e=>e.value);const result=await api('scenario',{contract:{version:1,name:f.name,source:{repo:setupSource.repo,ref:setupSource.commit,files},image:f.image,setup:f.setup.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),goal:f.goal,steps:[{id:'goal',title:f.check_title,probe:f.probe}]}});form.elements.scenario.value=result.path;if(!form.elements.title.value)form.elements.title.value=f.name;dirty=true;$('#preview').hidden=true;$('#notice').textContent='Scenario saved privately. Choose your two documents below, then preview the exact source, task and check before starting.';form.scrollIntoView({behavior:'smooth'});}catch(e){error(e);}};
