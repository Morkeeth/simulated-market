'use strict';
const $=s=>document.querySelector(s);
let token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem('workspace-token')||'';
if(token){sessionStorage.setItem('workspace-token',token);history.replaceState(null,'',location.pathname);}
let current=null,timer=null,launching=null;
async function api(path,body){const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'X-Workspace-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.error);return d;}
function node(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n;}
function detail(title,value,parent){const d=node('details','',parent);node('summary',title,d);node('pre',JSON.stringify(value,null,2),d);}
function error(e){$('#error').textContent=e.message;}
function pendingEpisode(e){return ['running','not_started'].includes(e.status);}
function callsLabel(rows){return rows.some(e=>!Number.isFinite(e.model_calls))?(rows.some(pendingEpisode)?'Pending':'Not recorded'):rows.reduce((sum,e)=>sum+e.model_calls,0)+' calls';}
function outcomeLabel(rows){return rows.some(pendingEpisode)?'Pending':rows.some(e=>typeof e.completed!=='boolean')?'Not recorded':rows.filter(e=>e.completed).length+'/'+rows.length;}
function show(data){
 if(data.kind==='mcp-recorded')return showMcp(data);
 $('#mcp-recorded').hidden=true;
 if(current?.id!==data.id){$('#policy').value=['local-model','local-shell-agent','tokenfactory-shell-agent'].includes(data.state?.policy)?data.state.policy:data.sponsor?'tokenfactory-shell-agent':'local-shell-agent';$('#sponsor-image-review').value='';}
 current=data;showPublicIdentity(data);showPublicCommands(data);for(const option of $('#policy').options)option.disabled=!!data.forecastOwned&&option.value!=='local-shell-agent';if(data.forecastOwned)$('#policy').value='local-shell-agent';$('#preview').hidden=false;$('#identity').replaceChildren();$('#create-panel').open=false;$('#journey').hidden=false;showForecast(data);showGlance(data);
 const c=data.contract,s=data.state;$('#journey a:last-child').href=data.decision_protocol?'#decision-protocol':'#release-review';showDecisions(data);showProtocol(data);showPreflight(data);showSponsor(data);$('#frozen-detail').open=!s||s.status==='prepared';node('h3',data.import?.label||c.name,$('#identity'));if(data.import){node('p','Imported display copy, not another run.',$('#identity'));if(data.import.note)node('p','Operator review note: '+data.import.note,$('#identity'));detail('Import identity and source',data.import,$('#identity'));};node('p',c.task.split('\n\n')[0],$('#identity'));if(c.task.includes('\n\n'))detail('Exact task and supplied interface help',c.task,$('#identity'));
 node('p','Frozen initial choice: '+choiceLabel(c.initial_choice)+'. '+c.seeds.length+' attempt'+(c.seeds.length===1?'':'s')+' per version, up to '+c.budget+' actions each.',$('#identity'));
 const facts=node('dl','',$('#identity'));facts.className='identity-grid';
 for(const [label,value] of [['Baseline commit',c.arms.base.commit],['Candidate commit',c.arms.head.commit],['Baseline files',Object.keys(c.arms.base.files).join(', ')],['Candidate files',Object.keys(c.arms.head.files).join(', ')],['Image',c.image],['Tool command',c.command.join(' · ')],['Setup',c.setup.join('\n')||'None'],['Agent documentation',c.discovery.path+' ('+c.discovery.source+')'],['Hidden evaluator',c.check.path+' at '+c.check.commit],['Frozen identity',c.sha256]]){node('dt',label,facts);node('dd',value,facts);}
 detail('All frozen file hashes and exact contract',c,$('#identity'));
 $('#start').disabled=!canStart(data);
 if(data.forecastOwned)node('p','Workspace-owned prospective batch. The sealed forecast is a fixed 50/50 baseline, not a learned prediction. Run evaluator controls before the local shell agents.',$('#identity'));
 else if(data.forecast_reference)node('p','Read-only imported controller batch. Opening this view does not launch an agent.',$('#identity'));
 else if(!data.allowAgents)node('p','Local execution is disabled for this workspace. Restart it with --allow-agents to enable running a newly prepared trial.',$('#identity'));
 if(data.forecastError)node('p','The reserved launch failed: '+data.forecastError,$('#identity')).className='err';
 if(!s||s.status==='prepared'){$('#results').hidden=true;return;}
 $('#results').hidden=false;$('#condition').textContent=data.import?.label||c.name;$('#status').textContent=(['complete','failed'].includes(s.status)?'Recorded trial: ':'Trial: ')+s.status+' · '+({ 'local-shell-agent':'mini-swe-agent with a local model','tokenfactory-shell-agent':s.provider_runtime_verified?'Token Factory model with local Docker':'hosted-policy trial; provider runtime not verified','local-model':'restricted local model agent','scripted-rehearsal':'scripted rehearsal, no model ran'}[s.policy]||'No execution yet')+(s.error?' · '+s.error:'');
 $('#summary').replaceChildren();$('#episodes').replaceChildren();$('#outcome-cards').replaceChildren();
 for(const arm of ['base','head']){const attempts=s.episodes.filter(e=>e.arm===arm),card=node('article','',$('#outcome-cards'));node('h3',arm==='base'?'Baseline':'Candidate',card);node('strong',attempts.length?outcomeLabel(attempts):'Pending',card);node('p','observed attempts passed the last task check',card);node('p',attempts.length+'/'+c.seeds.length+' planned attempts recorded · '+callsLabel(attempts)+' · model requests',card);}
 const table=node('table','',$('#summary'));const row=node('tr','',table);
 for(const h of ['Version','Attempts','Read docs','Setup passed','Invoked','Exit 0','Last task check','Ever passed','Recovered'])node('th',h,row);
 for(const arm of ['base','head']){const rows=s.episodes.filter(e=>e.arm===arm),r=node('tr','',table);node('td',arm,r);node('td',String(rows.length)+'/'+c.seeds.length,r);for(const key of ['discovered','setup_ok','invoked','valid_invocation','completed','ever_completed','recovered'])node('td',key==='completed'&&rows.some(pendingEpisode)?'pending':rows.some(e=>e[key]===null)?'not classified':rows.filter(e=>e[key]).length+'/'+rows.length,r);}
 if(s.policy==='tokenfactory-shell-agent')node('p',s.model?.runtime==='LOCAL_HTTP_TEST_DOUBLE'?'Local HTTP test double. These calls exercise the provider interface without hosted inference.':s.provider_runtime_verified?'Provider response recorded. Tool execution used local Docker.':'Provider runtime unverified. Inspect the recorded attempts and failure stage.',$('#episodes'));
 if(s.model)detail('Actual agent runtime',s.model,$('#episodes'));
 if(s.cost)detail('Measured cost scope',s.cost,$('#episodes'));
 if(s.policy==='local-shell-agent')node('p',c.artifact?'Shell coding agent: the final file is checked separately. The agent may use the supplied tool or its own method.':'Shell coding agent: setup and input freezing are controller-owned. Only registered tool invocations can pass the task check; direct source calls and printed claims cannot.',$('#episodes'));
 if(s.policy==='scripted-rehearsal')node('p','SCRIPTED REHEARSAL: fixed actions exercised real tool code. No model ran; this is not evidence of agent behavior.',$('#episodes'));
 for(const ep of s.episodes){const card=node('article','',$('#episodes'));card.id='episode-'+ep.arm+'-'+ep.seed;node('h3',(ep.arm==='base'?'Baseline':'Candidate')+' · seed '+ep.seed+' · '+ep.status,card);node('p',pendingEpisode(ep)?'No final task verdict yet.':typeof ep.completed!=='boolean'?'Task verdict not recorded.':ep.completed?'Last registered task check passed.':'Last registered task check did not pass.',card);if(ep.error)node('p',ep.error,card);node('p',callsLabel([ep])+'. Usage: '+JSON.stringify(ep.usage),card);if(ep.shell_trace)detail('Actual shell commands and outputs',ep.shell_trace,card);for(const [i,e] of ep.events.entries())eventDetail(i,e,card);}
}
async function poll(){clearTimeout(timer);if(!current)return;const id=current.id;try{const d=await api('tool/'+id);if(current?.id!==id)return;show(d);if(d.state.status==='running'||d.forecastLaunching||d.state.status==='prepared'&&launching===id&&!d.forecastError||['queued','running'].includes(d.preflight?.state.status))timer=setTimeout(poll,2000);else launching=null;}catch(e){error(e);}}
async function saved(){const d=await api('tools');guidePaid=d.allowSponsor===true;publicGuide.textContent=guidePaid?'Ask the Nemotron guide · one paid model turn':'Check the supported path · no model call';publicGuide.disabled=false;$('#model-smoke-run').disabled=!guidePaid;$('#saved').replaceChildren();for(const x of d.trials){const b=node('button',(x.import?.label||x.contract.name)+' · '+x.state.status,$('#saved'));b.onclick=async()=>{clearTimeout(timer);try{const fresh=await api('tool/'+x.id);show(fresh);if(fresh.state.status==='running'||fresh.forecastLaunching||['queued','running'].includes(fresh.preflight?.state.status))timer=setTimeout(poll,2000);}catch(e){error(e);}};}
 const workshopCases=d.trials.filter(x=>x.import&&/^(Helpful|Harmful) ·/.test(x.import.label));
 $('#workshop-replays').hidden=!workshopCases.length;$('#workshop-case-buttons').replaceChildren();
 for(const x of workshopCases){const b=node('button',x.import.label,$('#workshop-case-buttons'));b.type='button';b.onclick=async()=>{try{clearTimeout(timer);const fresh=await api('tool/'+x.id);$('#workspace-after-sample').hidden=false;show(fresh);window.dispatchEvent(new CustomEvent('retained-swarm',{detail:fresh}));$('#swarm-example').scrollIntoView({behavior:'auto',block:'start'});}catch(e){error(e);}};}
 const latestLive=[...d.trials].reverse().find(x=>x.state.status==='complete'&&x.state.policy==='tokenfactory-shell-agent'&&x.state.provider_runtime_verified&&x.providerReceipt?.matched_replies);
 const liveBox=$('#latest-live-run');liveBox.hidden=!latestLive;
 if(latestLive){
  const r=latestLive.providerReceipt,s=latestLive.state;
  const arms=arm=>s.episodes.filter(e=>e.arm===arm);
  const outcome=arm=>arms(arm).filter(e=>e.completed).length+'/'+arms(arm).length;
  $('#latest-live-title').textContent=latestLive.import?.label||latestLive.contract.name;
  $('#latest-live-outcome').textContent='Agents finished: before '+outcome('base')+' · after '+outcome('head')+'. '+(s.episodes.every(e=>!e.completed)?'Neither version got them to the finish.':'Watch where their paths split.');
  $('#latest-live-receipt').textContent='Provider receipt: '+r.matched_replies+' matched '+r.model+' replies · '+(r.usage_totals.prompt_tokens||0)+' input and '+(r.usage_totals.completion_tokens||0)+' output tokens'+(r.request_ids.length?' · first request '+r.request_ids[0]:'')+' · $'+Number(r.controller_cost?.accounted_usd||0).toFixed(8)+' controller list-price estimate, not an invoice.';
  $('#latest-live-open').onclick=async()=>{const fresh=await api('tool/'+latestLive.id);$('#workspace-after-sample').hidden=false;show(fresh);$('#results').scrollIntoView({behavior:'smooth',block:'start'});};
 }
 const latest=[...d.trials].reverse().find(x=>x.publicPr&&x.state.status==='complete');
 if(!current&&latest){show(latest);$('#workspace-after-sample').hidden=false;publicTrial=latest.id;publicStatus.textContent='Recorded local result: before '+latest.state.episodes.filter(e=>e.arm==='base'&&e.completed).length+'/'+latest.state.episodes.filter(e=>e.arm==='base').length+' finished; after '+latest.state.episodes.filter(e=>e.arm==='head'&&e.completed).length+'/'+latest.state.episodes.filter(e=>e.arm==='head').length+' finished. Reopening makes no model call.';}
}
$('#prepare').onclick=async()=>{try{$('#error').textContent='';clearTimeout(timer);const d=await api('tool/prepare',{contract:JSON.parse($('#contract').value)});show(d);await saved();}catch(e){error(e);}};
$('#start').onclick=async()=>{try{$('#start').disabled=true;launching=current.id;await api('tool/start',{id:current.id,expected:current.contract.sha256,policy:$('#policy').value,...($('#policy').value==='tokenfactory-shell-agent'?{sponsorPreview:current.sponsor?.preview.sha256,sponsorConsent:$('#sponsor-consent').checked?current.sponsor?.preview.sha256:null}:{})});timer=setTimeout(poll,1000);}catch(e){launching=null;error(e);$('#start').disabled=!canStart(current);}};
$('#import').onclick=async()=>{try{$('#error').textContent='';const data=await api('tool/import',{path:$('#import-path').value,label:$('#import-label').value,note:$('#import-note').value});clearTimeout(timer);show(data);await saved();}catch(e){error(e);}};
if(token)saved().catch(error);

let publicTrial=null;
const publicStatus=$('#public-pr-status');
const publicRun=$('#public-pr-live');
const publicPrepare=$('#public-pr-prepare');
const publicGuide=$('#public-pr-guide');
let guidePaid=false;
publicGuide.disabled=true;
function showGuide(data){
 const answer=$('#public-pr-guide-answer');
 answer.hidden=false;
 answer.textContent=data.guide+(data.proposed_task?' Task: '+data.proposed_task:'')+(data.check?' Check: '+data.check:'')+' · '+(data.model_calls?'Real Nemotron, '+data.model_calls+' model call.':'No model call.');
}
publicGuide.onclick=async()=>{
 const answer=$('#public-pr-guide-answer');
 publicGuide.disabled=true;answer.hidden=false;answer.textContent=guidePaid?'The guide is reading the public PR. One paid Nemotron call may run.':'Checking the supported path. Paid model calls are disabled in this local workspace.';
 try{
  const data=await api('swarm/guide',{pr_url:$('#public-pr-url').value.trim()});
  showGuide(data);
 }catch(e){answer.textContent=e.message;}
 finally{publicGuide.disabled=false;}
};
// Historical guide advice can predate the recorded result. Request current local guidance explicitly.
function clearPublicResult(){
 $('#public-pr-entry').classList.remove('is-complete');
 $('#public-pr-kicker').textContent='START WITH A CHANGE';
 $('#public-pr-heading').textContent='Watch the example. Check your PR.';
 $('#public-pr-identity').hidden=true;
 $('#public-pr-trace').hidden=true;
 $('#workspace-after-sample').hidden=true;
}
function showPublicIdentity(data){
 const box=$('#public-pr-identity');
 if(!data.publicPr){box.hidden=true;return;}
 const completed=data.state.status==='complete';
 const realHosted=completed&&data.state.policy==='tokenfactory-shell-agent'&&data.state.provider_runtime_verified;
 $('#public-pr-entry').classList.toggle('is-complete',completed);
 $('#public-pr-kicker').textContent=realHosted?'REAL NEMOTRON · LOCAL SANDBOX':completed?'RECORDED LOCAL RUN':'GETTING THE CHANGE READY';
 $('#public-pr-heading').textContent=completed?(data.publicPr.url==='https://github.com/python/cpython/pull/29858'?'A blank line split the two attempts.':'An agent tried both versions in this saved run.'):'This PR has a registered task and local checks.';
 box.hidden=false;box.replaceChildren();
 node('strong',data.publicPr.title||data.contract.name,box);
 node('p','Original '+data.publicPr.base+' · Proposed '+data.publicPr.head,box);
 node('p','Fetched from '+data.publicPr.url+' · '+(data.publicPr.pr_state||'pinned source'),box);
}
function showPublicCommands(data){
 const box=$('#public-pr-trace');box.replaceChildren();
 const arms=data.liveCommands||[];
 box.hidden=!arms.some(arm=>arm.steps.length);
 if(box.hidden)return;
 node('h3','What each agent actually ran',box);
 const compare=node('div','',box);compare.className='public-pr-compare';
 for(const arm of arms){
  const ep=data.state.episodes.find(e=>e.arm===arm.arm&&e.seed===arm.seed);
  const card=node('article','',compare);card.className='public-pr-arm';
  node('h4',(arm.arm==='base'?'Original':'Proposed')+' · '+(ep?.model_calls??'?')+' model calls',card);
  const list=node('ol','',card);
  for(const step of arm.steps){
   const line=node('li','',list);
   node('code',step.command,line);
   const note=step.returncode===0?'exit 0':'exit '+step.returncode+(step.output?' · '+step.output.trim().split('\n')[0]:'');
   node('small',note,line);
  }
 }
 if(data.state.status==='complete'){
  const episodes=data.state.episodes;
  const both=episodes.length===2&&episodes.every(e=>e.completed);
  const base=arms.find(arm=>arm.arm==='base'),head=arms.find(arm=>arm.arm==='head');
  const friction=base?.steps.some(step=>step.returncode!==0)&&base.steps.some(step=>step.command.includes("awk 'NF'"))&&head?.steps.every(step=>step.returncode===0);
  node('p',both?(friction?'Both finished. The original cost the agent one failure and a workaround.':'Both finished the task.'):'Read the separate task checks below for the final verdict.',box).className='public-pr-verdict';
  node('p','One run, one model. No general effect measured.',box).className='public-pr-limit';
 }
}
async function watchPublicTrial(id){
 const data=await api('tool/'+id);
 show(data);
 showPublicIdentity(data);showPublicCommands(data);
 if(data.state.status==='running'||data.state.status==='prepared'&&launching===id){
   publicStatus.textContent=(data.liveCommands||[]).some(arm=>arm.steps.length)?'Live agent commands are appearing below. The independent task check is still pending.':'Waiting for the agent’s first command. The task check is still pending.';
   setTimeout(()=>watchPublicTrial(id).catch(e=>{publicStatus.textContent=e.message;}),2000);
 }else{
   launching=null;
   publicStatus.textContent=data.state.status==='complete'?'Live run finished. Read the original and proposed attempts and the separate task checks below.':'Live run stopped. Inspect the retained attempt and failure stage below.';
   $('#results').scrollIntoView({behavior:'smooth',block:'start'});
 }
}
$('#public-pr-form').onsubmit=async event=>{
 event.preventDefault();publicPrepare.disabled=true;publicRun.hidden=true;clearPublicResult();
 publicStatus.textContent='Fetching the change and finding a task agents could try. No agent has started.';
 try{
   if(!token)throw Error('Open the private session link printed by the local workspace first.');
   const lookup=await api('tool/public-pr/inspect',{url:$('#public-pr-url').value.trim()});
   if(lookup.status==='recorded_result'){
     publicTrial=lookup.trial.id;
     $('#workspace-after-sample').hidden=false;
     show(lookup.trial);
     publicStatus.textContent='Saved result reopened for this exact link. No new agent or model request was made.';
     return;
   }
   if(lookup.status!=='registered_unrun'){
     $('#public-pr-heading').textContent=lookup.status==='supported_check'?'The change has a test agents could try.':'This change needs more setup.';
     publicStatus.textContent=lookup.status==='supported_check'?'The test breaks before the change and works after it. Agents have not tried this PR yet.':'Agents have not tried this PR yet. '+lookup.reason;
     if(lookup.base&&lookup.head){
       const box=$('#public-pr-identity');box.replaceChildren();box.hidden=false;
       node('strong',lookup.title||'Pinned public PR',box);
       const proof=node('details','',box);node('summary','How we know',proof);
       node('p','Before '+lookup.base+' · After '+lookup.head,proof);
       if(lookup.selected_test)node('p','Test: '+lookup.selected_test,proof);
       if(lookup.controls)for(const [name,row] of Object.entries(lookup.controls))node('p',name+': '+(row.passed?'pass':'fail')+' · '+row.tests_run+' tests run',proof);
       node('p',lookup.reason,proof);
     }
     return;
   }
   publicStatus.textContent='This change has a task. Checking both versions before agents start.';
   const data=await api('tool/public-pr',{url:lookup.url});
   publicTrial=data.id;
   $('#workspace-after-sample').hidden=false;
   show(data);
   let checked=data;
   for(let attempt=0;attempt<90;attempt++){
     if(checked.preflight?.state.status==='complete'||checked.preflight?.state.status==='failed')break;
     await new Promise(resolve=>setTimeout(resolve,2000));
     checked=await api('tool/'+data.id);
   }
   show(checked);
   if(checked.preflight?.state.status!=='complete'||!checked.preflight.state.passed){
     throw Error('The independent control did not pass. Inspect the task and checker below; no model call was made.');
   }
   publicStatus.textContent='Both versions are ready for an agent run. Agents have not tried this link in this workspace yet.';
 }catch(e){publicStatus.textContent=e.message;}
 finally{publicPrepare.disabled=false;}
};
publicRun.onclick=async()=>{
 if(!publicTrial||!current?.sponsor)return;
 publicRun.disabled=true;
 const id=publicTrial,digest=current.sponsor.preview.sha256;
 try{
   launching=id;
   await api('tool/start',{id,expected:current.contract.sha256,policy:'tokenfactory-shell-agent',sponsorPreview:digest,sponsorConsent:digest});
   publicStatus.textContent='Starting the live NVIDIA agent. The controller reserved the worst-case cost before any model request.';
   await watchPublicTrial(id);
 }catch(e){launching=null;publicStatus.textContent=e.message;publicRun.disabled=false;}
};

function showModelSmoke(receipt){
 const box=$('#model-smoke-receipt');box.replaceChildren();
 if(receipt.state==='not_run'){$('#model-smoke-status').textContent='No separate connection-check request has run in this workspace. Open the private run above for its provider receipt.';return;}
 box.hidden=false;$('#model-smoke-run').disabled=true;
 $('#model-smoke-status').textContent=receipt.state==='complete'?'Provider response saved in this private workspace.':receipt.state==='running'?'Request reserved. Reload to check its outcome.':'Request stopped. Billing status may be unknown.';
 if(receipt.state==='complete'){
  node('p','Provider model: '+receipt.model,box);
  node('p','Reply: '+receipt.reply,box);
  node('p','Usage: '+JSON.stringify(receipt.usage),box);
  node('p','Estimated list-price cost: '+(receipt.estimated_usd===null?'unknown':'USD '+receipt.estimated_usd)+'. Actual charge is unknown.',box);
  node('p','Provider request ID: '+(receipt.request_id||'not returned'),box);
 }else if(receipt.error_type)node('p','Stopped: '+receipt.error_type,box);
 node('p',receipt.scope,box);
 detail('Private receipt file',receipt.receipt,box);
}
api('model-smoke').then(showModelSmoke).catch(e=>{$('#model-smoke-status').textContent=e.message;});
$('#model-smoke-run').onclick=async()=>{
 const button=$('#model-smoke-run');button.disabled=true;
 $('#model-smoke-status').textContent='Waiting for one provider response. No automatic retry.';
 try{showModelSmoke(await api('model-smoke/run',{}));}
 catch(e){$('#model-smoke-status').textContent=e.message;try{showModelSmoke(await api('model-smoke'));}catch{} }
};

// Guided fields produce the same versioned contract as the expert path.
const loaded={source:null,fixture:null,check:null};
const builderSteps=[...document.querySelectorAll('.builder-step')];
const stepTitles=['Tool versions','The agent task','Independent check','Your decision'];
const stepHelp=[
 'Start with two committed versions of your tool. We will read their files before you select what the agent can see.',
 'Describe one result an agent must produce, then choose its local image, command and supplied documentation.',
 'Pick a separate committed evaluator. The agent will not see its source during the attempt.',
 'Set a bounded attempt budget and record your release choice before any result is shown.'
];
let builderStep=0;
function setBuilderStep(index){
 builderStep=index;
 builderSteps.forEach((step,i)=>step.hidden=i!==index);
 $('#builder-progress').textContent=`Step ${index+1} of 4 · ${stepTitles[index]}`;
 $('#builder-help').textContent=stepHelp[index];
 $('#builder-meter-fill').style.width=((index+1)*25)+'%';
 $('#create-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
function stepError(message){$('#error').textContent=message;$('#error').scrollIntoView({behavior:'smooth'});}
function stepValid(index){
 const panel=builderSteps[index];
 for(const field of panel.querySelectorAll('input[required],textarea[required],select[required]')){
  if(field.closest('[hidden]'))continue;
  if(!field.reportValidity())return false;
 }
 if(index===0){
  if(!loaded.source){stepError('Read the committed versions before continuing.');return false;}
  if(!picked('source').length){stepError('Select at least one tool file.');return false;}
 }
 if(index===1){
  if($('#fixture-repo').value.trim()&&(!loaded.fixture||!picked('fixture').length)){
   stepError('Read and select fixture files, or clear the optional fixture repository.');return false;
  }
 }
 if(index===2&&!loaded.check){stepError('Read the independent evaluator files before continuing.');return false;}
 return true;
}
for(const button of document.querySelectorAll('.builder-next'))button.onclick=()=>{
 $('#error').textContent='';if(stepValid(builderStep))setBuilderStep(builderStep+1);
};
for(const button of document.querySelectorAll('.builder-back'))button.onclick=()=>{
 $('#error').textContent='';setBuilderStep(builderStep-1);
};
function setWorking(button,status,message){
 const original=button.textContent;
 button.disabled=true;button.classList.add('builder-busy');
 status.setAttribute('aria-busy','true');status.textContent=message;
 return ()=>{button.disabled=false;button.classList.remove('builder-busy');status.removeAttribute('aria-busy');button.textContent=original;};
}
$('#prospective').onchange=()=>{$('#prospective-fields').hidden=!$('#prospective').checked;};
const lines=value=>value.split('\n').map(x=>x.trim()).filter(Boolean);
function picked(kind){return [...document.querySelectorAll('#'+kind+'-files input:checked')].map(x=>x.value);}
function options(select,values,placeholder){const previous=select.value;select.replaceChildren();const blank=node('option',placeholder,select);blank.value='';for(const value of values){const o=node('option',value,select);o.value=value;}if(values.includes(previous))select.value=previous;}
function fileCounts(){for(const kind of ['source','fixture'])$('#'+kind+'-count').textContent=picked(kind).length+' files selected';}
function filterFiles(kind){const query=$('#'+kind+'-filter').value.toLowerCase();for(const label of document.querySelectorAll('#'+kind+'-files label'))label.hidden=!label.textContent.toLowerCase().includes(query);}
for(const kind of ['source','fixture'])$('#'+kind+'-filter').oninput=()=>filterFiles(kind);
function discovery(){fileCounts();options($('#discovery'),[...picked('source').filter(path=>loaded.source?.files.find(f=>f.path===path)?.presence?.base&&loaded.source?.files.find(f=>f.path===path)?.presence?.head),...picked('fixture')],'Choose a supplied document');}
function stale(kind){loaded[kind]=null;$('#'+kind+'-status').textContent='Read this source again to pin the changed selection.';if(kind==='check')options($('#check-path'),[],'Read evaluator files');else{$('#'+kind+'-files').replaceChildren();discovery();}}
function edit(){if(current){$('#preview').hidden=true;$('#results').hidden=true;$('#release-review').hidden=true;$('#forecast').hidden=true;$('#journey').hidden=true;$('#glance').hidden=true;clearTimeout(timer);current=null;}}
$('#builder').addEventListener('input',event=>{if(!event.target.id.endsWith('-filter'))edit();});
for(const kind of ['source','fixture','check']){
 for(const suffix of kind==='source'?['repo','base','head']:['repo','ref'])$('#'+kind+'-'+suffix).addEventListener('input',()=>stale(kind));
 $('#'+kind+'-load').onclick=async()=>{
  const button=$('#'+kind+'-load');const status=$('#'+kind+'-status');const done=setWorking(button,status,kind==='source'?'Reading committed tool files…':kind==='check'?'Reading committed evaluator files…':'Reading committed task inputs…');
  try{
   $('#error').textContent='';const repo=$('#'+kind+'-repo').value;
   const base=$('#'+kind+(kind==='source'?'-base':'-ref')).value,head=kind==='source'?$('#source-head').value:base;
   const signature=JSON.stringify({repo,base,head});
   const d=await api('tool/source',{repo,base,head});
   const now={repo:$('#'+kind+'-repo').value,base:$('#'+kind+(kind==='source'?'-base':'-ref')).value,head:kind==='source'?$('#source-head').value:$('#'+kind+'-ref').value};
   if(JSON.stringify(now)!==signature)return;
   loaded[kind]=d;$('#'+kind+'-status').textContent=(kind==='source'?'Baseline '+d.commits.base+' · Candidate '+d.commits.head:'Commit '+d.commits.base)+'. '+d.scope;
   if(kind==='check')options($('#check-path'),d.files.filter(f=>f.available&&f.path.endsWith('.py')).map(f=>f.path),'Choose the independent evaluator');
   else{
    const container=$('#'+kind+'-files');container.replaceChildren();
    for(const f of d.files){const label=node('label','',container),input=document.createElement('input');input.type='checkbox';input.value=f.path;input.disabled=!f.available;input.addEventListener('change',discovery);label.append(input,document.createTextNode(f.path+(!f.available?' · unsupported file type':!f.presence.base?' · added in candidate':!f.presence.head?' · removed in candidate':f.changed?' · changed':'')));}
    discovery();
   }
   if(kind!=='check')filterFiles(kind);
   if(kind==='source'){const list=$('#source-refs');list.replaceChildren();for(const ref of d.refs){const o=node('option','',list);o.value=ref;}}
  }catch(e){stale(kind);error(e);}finally{done();}
 };
}
$('#images-load').onclick=async()=>{const button=$('#images-load');const done=setWorking(button,$('#image-status'),'Reading cached local images…');try{
 const d=await api('tool/images',{}),select=$('#image');select.replaceChildren();const blank=node('option','Choose a cached image',select);blank.value='';
 for(const row of d.images){const option=node('option',(row.names.join(', ')||'Untagged image')+' · '+row.id.slice(0,23),select);option.value=row.id;}
 $('#image-status').textContent=d.scope+(d.images.length?' Choose an image with Python 3 and bash.':' No cached image is available. Prepare one locally before creating a trial.');
}catch(e){error(e);}finally{done();}};
$('#builder').onsubmit=async event=>{event.preventDefault();if(!stepValid(builderStep))return;const button=$('#guided-prepare');const done=setWorking(button,$('#prepare-status'),'Freezing source bytes and preparing the local comparison…');try{
 $('#error').textContent='';if(!loaded.source||!loaded.check)throw Error('Read the tool versions and evaluator files before freezing.');
 const files=picked('source');if(!files.length)throw Error('Select the committed tool files to include in both versions.');
 const rawSeeds=$('#seeds').value.split(',').map(x=>x.trim());if(rawSeeds.some(x=>!/^[-+]?\d+$/.test(x)))throw Error('Seeds must be whole numbers separated by commas.');
 const seeds=rawSeeds.map(Number);if(seeds.some(x=>!Number.isSafeInteger(x)))throw Error('Choose safe whole-number seeds.');
 const c={version:1,name:$('#trial-name').value.trim(),repo:loaded.source.repo,base:loaded.source.commits.base,head:loaded.source.commits.head,files,discovery:$('#discovery').value,image:$('#image').value,setup:lines($('#setup').value),command:lines($('#command').value),task:$('#task').value.trim(),check:{repo:loaded.check.repo,ref:loaded.check.commits.base,path:$('#check-path').value},budget:Number($('#budget').value),seeds,initial_choice:$('#choice').value};
 if($('#fixture-repo').value.trim()){if(!loaded.fixture)throw Error('Read the fixture source again before freezing.');const selected=picked('fixture');if(!selected.length)throw Error('Select at least one fixture file or clear the optional fixture repository.');c.fixtures={repo:loaded.fixture.repo,ref:loaded.fixture.commits.base,files:selected};}
 $('#contract').value=JSON.stringify(c,null,2);clearTimeout(timer);
 const prospective=$('#prospective').checked;
 const body=prospective?{contract:c,modelSnapshot:$('#model-snapshot').value.trim(),population:{kind:'local-shell-agent',description:$('#population-description').value.trim()},taskFamily:{name:$('#task-family-name').value.trim(),sampling:$('#task-family-sampling').value.trim()}}:{contract:c};
 show(await api(prospective?'tool/prospective-prepare':'tool/prepare',body));await saved();$('#preview').scrollIntoView({behavior:'smooth'});
}catch(e){error(e);$('#error').scrollIntoView({behavior:'smooth'});}finally{done();}};


const choiceLabel=value=>({base:'Keep the baseline',head:'Ship the candidate',defer:'Defer the release decision'}[value]||value);
function showDecisions(data){
 const ready=!data.decision_protocol&&['complete','failed'].includes(data.state?.status);$('#release-review').hidden=!ready;if(!ready)return;
 const rows=data.decisions||[],latest=rows.at(-1),summary=$('#decision-comparison');summary.replaceChildren();
 node('p','Frozen initial choice: '+choiceLabel(data.contract.initial_choice)+'.',summary);
 node('p',latest?'Latest reviewed choice: '+choiceLabel(latest.choice)+' (revision '+latest.revision+').':'Reviewed choice: not recorded.',summary);
 const episodes=data.state.episodes;
 for(const arm of ['base','head']){const subset=episodes.filter(e=>e.arm===arm);node('p',(arm==='base'?'Baseline':'Candidate')+': '+subset.filter(e=>e.completed).length+'/'+subset.length+' observed attempts passed the last task check; '+subset.length+'/'+data.contract.seeds.length+' planned attempts recorded.',summary);}
 if(data.state.status==='failed')node('p','Execution ended with an error. Inspect partial attempts before deciding.',summary);
 if(data.state.policy==='scripted-rehearsal')node('p','These outcomes come from scripted infrastructure checks. No model ran.',summary);
 $('#decision-history').replaceChildren();for(const row of rows){const card=node('details','',$('#decision-history'));node('summary','Revision '+row.revision+' · '+choiceLabel(row.choice)+' · '+new Date(row.at).toLocaleString(),card);node('p',row.reason,card);detail('Exact trial and outcome binding',row,card);}
 $('#reviewed-choice').value='';$('#decision-reason').value='';$('#decision-status').textContent=latest?'Saved revision '+latest.revision+'.':'';
}
$('#decision-form').onsubmit=async event=>{event.preventDefault();const button=$('#save-decision');button.disabled=true;try{
 $('#error').textContent='';const data=await api('tool/decision',{id:current.id,expected:current.contract.sha256,state_sha256:current.state_sha256,revision:(current.decisions||[]).length,choice:$('#reviewed-choice').value,reason:$('#decision-reason').value});show(data);await saved();$('#decision-status').textContent='Reviewed decision saved as revision '+data.decisions.length+'. Earlier choices and trial evidence are preserved.';
}catch(e){error(e);}finally{button.disabled=false;}};


function showForecast(data){
 $('#forecast').hidden=false;const panel=$('#forecast-content');panel.replaceChildren();const view=data.forecast||{status:'absent'};
 const status=node('p',view.status==='sealed-hidden'?'Forecast hidden':view.status==='scored'?(view.mode==='historical-fixture'?'Historical fixture score':'Scored against the reserved later batch'):'Not scored',panel);status.className='forecast-state';
 if(view.status==='absent')node('p','No sealed forecast is linked to this exact trial. Existing exploratory attempts cannot be relabeled as later validation.',panel);
 else if(view.status==='sealed-hidden')node('p','The forecast was sealed. Its probabilities and score stay hidden until the eval-only choice is saved and you explicitly reveal it.',panel);
 else if(view.status==='invalid')node('p','The linked forecast could not be verified: '+view.error,panel);
 else{
  const f=view,r={seeds:data.contract.seeds,mode:view.mode};node('p','Sealed task-completion probabilities: baseline '+probability(f.probabilities.base)+'; candidate '+probability(f.probabilities.head)+'.',panel);
  node('p','Forecast source: '+view.forecast_source+'.',panel);
  if(f.abstention_reason)node('p','Abstention: '+f.abstention_reason,panel);
  node('p','Reserved batch: '+r.seeds.length+' attempt'+(r.seeds.length===1?'':'s')+' per version. Evidence mode: '+r.mode+'.',panel);
  if(view.status!=='scored')node('p',view.reason||'A verified complete later batch is required before a score can be shown.',panel);
  if(view.status==='scored'){
   const e=view.score;node('p','Forecast Brier loss: '+metric(e.brier)+' · constant-half baseline on matched attempts: '+metric(e.baseline_brier_matched)+'. Lower is better.',panel);
   if(e.brier!==null&&e.brier===e.baseline_brier_matched)node('p','The forecast ties the constant-half baseline. No score advantage is observed.',panel);
   if(e.direction)node('p','Direction verdict: '+e.direction.verdict+'.',panel);
   node('p',e.n_scored+'/'+e.n_reserved+' reserved outcomes scored. Coverage: '+Math.round(e.coverage*100)+'%.',panel);
   for(const arm of ['base','head'])node('p',(arm==='base'?'Baseline':'Candidate')+' later batch: '+e.counts[arm].reached+'/'+e.counts[arm].n+' task checks passed.',panel);
   node('p',e.claim+'. '+e.limits,panel);
  }
  detail('Verified forecast identity and receipts',{reference:data.forecast_reference,contract:view.contract,seal:view.seal,labels:view.labels,mode:view.mode,source:view.forecast_source},panel);
 }
 node('p','This shows the forecast-to-result workflow, not predictive advantage. A seal records the prediction before the reserved controller run. Local integrity checks do not independently attest chronology or independence. A single comparison does not establish calibrated advantage.',panel).className='small';
}
function probability(value){return value===null?'abstained':(value*100).toFixed(1)+'%';}
function metric(value){return value===null?'not scored':value.toFixed(6);}
$('#forecast-open').onclick=async()=>{const button=$('#forecast-open');button.disabled=true;try{
 $('#error').textContent='';const data=await api('tool/forecast',{path:$('#forecast-path').value,decisionProtocol:$('#decision-protocol-enable').checked});show(data);await saved();$('#glance').scrollIntoView({behavior:'smooth'});
}catch(e){error(e);}finally{button.disabled=false;}};

function eventDetail(index,event,parent){
 if(event.action!=='invoke'){detail((index+1)+'. '+event.action,event,parent);return;}
 const observation=event.observation||{},check=event.check;
 const box=node('details','',parent);node('summary',(index+1)+'. Tool invocation · exit '+observation.returncode+' · '+(check?.passed?'task check passed':'task check did not pass'),box);
 if(observation.args)node('pre','tool '+observation.args.map(a=>JSON.stringify(a)).join(' '),box);
 node('p','Actual tool output',box);node('pre',observation.output||'(empty)',box);
 if(check){node('p','Independent checker: '+(check.passed?'passed':'did not pass')+'. '+check.source,box);if(check.output)node('pre',check.output,box);}
 detail('Full controller record',event,box);
}

function showGlance(data){
 const box=$('#glance');box.hidden=false;box.replaceChildren();const c=data.contract,state=data.state,view=data.forecast;
 const hidden=view?.status==='sealed-hidden',verified=view&&['sealed-unscored','scored'].includes(view.status),scored=view?.status==='scored';
 node('p',state?.policy==='scripted-rehearsal'?'SIMULATED · LOCAL · SCRIPTED':state?.policy==='tokenfactory-shell-agent'?(state.model?.runtime==='LOCAL_HTTP_TEST_DOUBLE'?'SIMULATED · LOCAL HTTP TEST DOUBLE':state.provider_runtime_verified?'RECORDED · REAL NEMOTRON · LOCAL SANDBOX':'LOCAL DOCKER · PROVIDER NOT VERIFIED'):'SIMULATED · LOCAL · VERSION COMPARISON',box).className='eyebrow';
 node('h2',data.import?.label||c.name,box);
 const task=node('details','',box);task.className='task-line';node('summary','One frozen task · read exact instructions',task);node('p',c.task,task);
 const source=node('details','',box);source.className='source-diff';node('summary','What changed in the frozen software?',source);const content=node('div','',source);node('p','Read the selected tool files from this trial’s frozen archives. Fixtures are excluded. This does not establish which change caused an outcome.',content);source.ontoggle=async()=>{if(!source.open||source.dataset.loaded)return;source.dataset.loaded='loading';try{const diff=await api('tool/source-diff',{id:data.id,expected:c.sha256});if(diff.contract!==c.sha256)throw Error('Source preview identity changed.');node('p','Source panes scroll. Preview limits: '+diff.limits.changed_files+' changed files, '+diff.limits.displayed_diff_lines+' diff lines and '+diff.limits.displayed_diff_characters+' characters. Source cap: '+diff.limits.source_bytes_per_file_per_arm+' bytes and '+diff.limits.source_lines_per_file_per_arm+' lines per file per version.',content);node('p',diff.changed_files+' changed / '+diff.selected_files+' selected files · '+diff.unchanged_files+' unchanged · '+diff.fixtures_excluded+' fixture files excluded.',content);for(const file of diff.files){const item=node('details','',content);node('summary',file.path+' · '+file.change+(file.status==='shown'?'':' · '+file.status),item);if(file.reason)node('p',file.reason+'. '+Object.values(file.source_bytes).reduce((a,b)=>a+b,0)+' source bytes omitted.',item);if(file.diff)node('pre',file.diff,item);if(file.omitted_diff_lines)node('p',file.omitted_diff_lines+' further diff lines omitted.',item);detail('Frozen file hashes',file.hashes,item);}node('p','Omitted: '+diff.omitted_files+' source files skipped, '+diff.omitted_source_bytes+' source bytes (both versions), '+diff.omitted_diff_lines+' diff lines. Byte omissions may include files whose line count was not read.',content);detail('Preview limits and exact trial identity',{contract:diff.contract,commits:diff.commits,limits:diff.limits},content);source.dataset.loaded='done';}catch(e){node('p','Source preview unavailable: '+e.message,content);source.dataset.loaded='error';}};
 const seal=node('div','',box);seal.className='seal-line';
 const stamp=node('span',hidden?'SEALED · HIDDEN':verified?(view.mode==='historical-fixture'?'FIXTURE':'SEALED'):(view?.status==='invalid'?'UNVERIFIED':'NO SEAL'),seal);stamp.className='seal-stamp'+(verified?'':' unsealed');
 node('span',hidden?'Save the eval-only choice before revealing this sealed forecast.':verified?view.forecast_source+' · before the reserved controller run':'No verified forecast linked to this trial. Not scored.',seal);
 const tracks=node('div','',box);tracks.className='path-tracks';
 for(const arm of ['base','head']){
  const episodes=(state?.episodes||[]).filter(e=>e.arm===arm),track=node('div','',tracks);track.className='path-track';
  const origin=node('div','',track);origin.className='path-stop';node('h3',arm==='base'?'Baseline':'Candidate',origin);node('code',c.arms[arm].commit.slice(0,8),origin);node('span','Frozen version',origin).className='stage';
  const prediction=node('div','',track);prediction.className='path-stop';node('strong',verified?(view.probabilities[arm]===null?'Abstain':probability(view.probabilities[arm]).replace('.0%','%')):hidden?'Hidden':'Not sealed',prediction).className='metric';node('span','Task-pass forecast',prediction).className='stage';
  const attempt=node('div','',track);attempt.className='path-stop';node('strong',state?.policy==='scripted-rehearsal'?'Scripted':episodes.length?callsLabel(episodes):'Pending',attempt).className='metric';node('span',episodes.length+'/'+c.seeds.length+' attempts recorded',attempt).className='stage';
  const checked=node('div','',track);checked.className='path-stop checked';node('strong',episodes.length?outcomeLabel(episodes):'Pending',checked).className='metric';node('span','Last task check passed',checked).className='stage';
  if(episodes.length){const link=node('a','Inspect actual path',checked);link.href='#episode-'+arm+'-'+episodes[0].seed;}
 }
 const score=node('div','',box);score.className='score-line';
 if(scored){const s=view.score,tie=s.brier!==null&&s.brier===s.baseline_brier_matched;node('strong',tie?'Forecast ties baseline':s.brier===null?'Forecast abstained':'Forecast scored',score);node('span','Brier '+compactMetric(s.brier)+' / baseline '+compactMetric(s.baseline_brier_matched)+' · '+s.n_scored+'/'+s.n_reserved+' scored'+(s.direction?' · '+s.direction.verdict:''),score);}
 else{node('strong',hidden?'Forecast hidden':'Not scored',score);node('span',hidden?'Record the eval-only choice before reveal.':verified?'Waiting for a verified complete later batch.':'No prospective score for these attempts.',score);}
 const choice=node('div','',box);choice.className='choice-line';const initial=node('div','',choice);node('small','Initial · frozen',initial);node('span',briefChoice(c.initial_choice),initial);node('span','→',choice).className='choice-arrow';const reviewed=node('div','',choice),latest=data.decision_protocol?[...data.decision_protocol.rows].reverse().find(r=>['eval_only','forecast_informed'].includes(r.stage)):data.decisions?.at(-1);node('small',latest?(data.decision_protocol?latest.stage.replaceAll('_',' '):'Reviewed · revision '+latest.revision):'Reviewed',reviewed);node('span',latest?briefChoice(latest.choice):'Not recorded',reviewed);
 node('p',hidden?'Direct agent results are visible. The sealed forecast and any score remain hidden until reveal. This sequence alone does not establish decision impact.':scored?'Workflow proof only. Same task; a single batch does not show predictive advantage. Local receipts do not independently attest chronology or independence.':'Recorded attempts, not adoption or decision-impact evidence. No verified later-batch score is available.',box).className='glance-limit';
 if(data.import?.note)node('p','Review note: '+data.import.note,box).className='glance-limit';
 const link=node('a','Inspect evidence and limits ↓',box);link.href='#forecast';link.className='evidence-link';
}
function briefChoice(value){return {base:'Keep baseline',head:'Ship candidate',defer:'Defer'}[value]||value;}

function compactMetric(value){return value===null?'not scored':String(Number(value.toFixed(6)));}


let preflightFor=null;
function canStart(data){const p=data.preflight;const hosted=$('#policy').value==='tokenfactory-shell-agent';return !data.forecastError&&!data.forecastLaunching&&(!data.forecastOwned||$('#policy').value==='local-shell-agent')&&(hosted?(data.allowSponsor&&data.sponsor?.preflight.status==='ready_to_call'&&data.sponsor.preview.evaluator_preflight.plan===p?.plan_sha256&&data.sponsor.preview.evaluator_preflight.result===p?.state.sha256&&$('#sponsor-consent').checked):data.allowAgents)&&data.state?.status==='prepared'&&p?.state.status==='complete'&&p.state.passed&&p.plan.policy===$('#policy').value;}
function addPreflightCase(kind,value=null){
 const host=$('#preflight-cases');if(host.children.length>=6)throw Error('Use at most six cases per preflight.');
 const card=node('div','',host);card.className='preflight-case';card.dataset.kind=kind;node('h4',kind==='valid'?'Known-valid task invocation':'Wrong-task variant',card);
 const field=(label,tag,key,text='')=>{const l=node('label',label,card),input=node(tag,'',l);input.dataset.key=key;input.required=true;input.value=text;return input;};
 field('Case name','input','label',value?.label||'');field('Why should the task accept or reject this?','textarea','reason',value?.reason||'');
 const args=field('Arguments appended to the tool prefix, one per line','textarea','args',(value?.args||[]).join('\n'));args.required=false;
 for(const arm of ['base','head']){const select=field((arm==='base'?'Baseline':'Candidate')+' expected task check','select',arm);for(const [v,text] of [['','Choose expected verdict'],['true','Accept'],['false','Reject']]){const o=node('option',text,select);o.value=v;}select.value=value?String(value.expected[arm]):'';}
 const remove=node('button','Remove case',card);remove.type='button';remove.onclick=()=>card.remove();
}
function showPreflight(data){
 const p=data.preflight,prepared=data.state?.status==='prepared'&&(!data.forecast_reference||data.forecastOwned)&&!data.forecastError;$('#preflight-panel').hidden=!prepared&&!p;if(!prepared&&!p)return;
 $('#preflight-form').hidden=!prepared;$('#run-preflight').disabled=['queued','running'].includes(p?.state.status);
 if(preflightFor!==data.id){preflightFor=data.id;$('#preflight-cases').replaceChildren();if(p)for(const c of p.plan.cases)addPreflightCase(c.kind,c);else{addPreflightCase('valid');addPreflightCase('wrong');}}
 const status=$('#preflight-status'),results=$('#preflight-results');results.replaceChildren();
 if(!p){status.textContent='Not checked. Evaluator preflight is required before this workspace starts an agent.';return;}
 status.textContent=p.state.status==='complete'?(p.state.passed?'All declared expectations matched. This checks these cases only.':'Expectations did not match. Agent execution is blocked; inspect each mismatch.'):'Evaluator controls: '+p.state.status;
 if(p.state.error)node('p',p.state.error,results);
 for(const row of p.state.rows){const c=p.plan.cases[row.case],d=node('details','',results);d.className='preflight-result';node('summary',(row.arm==='base'?'Baseline':'Candidate')+' · '+c.label+' · expected '+(row.expected?'accept':'reject')+' · '+(row.error?'execution error':row.check?.passed?'accepted':'rejected')+' · '+(row.matched?'matched':'MISMATCH'),d);node('p',c.reason,d);if(row.observation)node('pre',row.observation.output||'(empty output)',d);detail('Actual command, setup and checker record',row,d);}
 detail('Frozen owner declarations and controller identity',p.plan,results);
}
$('#add-valid-case').onclick=()=>{try{addPreflightCase('valid');}catch(e){error(e);}};
$('#add-wrong-case').onclick=()=>{try{addPreflightCase('wrong');}catch(e){error(e);}};
$('#policy').onchange=()=>{$('#sponsor-consent').checked=false;if(current){showSponsor(current);$('#start').disabled=!canStart(current);}};
$('#preflight-form').onsubmit=async event=>{event.preventDefault();const button=$('#run-preflight');button.disabled=true;try{
 const cases=[...$('#preflight-cases').children].map(card=>{const value=key=>card.querySelector('[data-key="'+key+'"]').value;return {kind:card.dataset.kind,label:value('label'),reason:value('reason'),args:lines(value('args')),expected:{base:value('base')==='true',head:value('head')==='true'}};});
 const data=await api('tool/preflight',{id:current.id,expected:current.contract.sha256,policy:$('#policy').value,cases});show(data);timer=setTimeout(poll,1000);
}catch(e){error(e);button.disabled=false;}};

let sponsorIdentity=null;
function showSponsor(data){
 const hosted=$('#policy').value==='tokenfactory-shell-agent',p=data.sponsor?.preview,gate=data.sponsor?.preflight;
 $('#sponsor-panel').hidden=!hosted;
 $('#sponsor-preview').hidden=data.state?.status!=='prepared'||!!data.import||!!data.forecast_reference;
 $('#sponsor-image-review').disabled=data.state?.status!=='prepared';
 $('#sponsor-consent').disabled=data.state?.status!=='prepared';
 const identity=data.id+':'+(p?.sha256||'')+':'+(data.preflight?.state.sha256||'');if(sponsorIdentity!==identity){sponsorIdentity=identity;$('#sponsor-consent').checked=false;}
 $('#start').textContent=hosted?'Start consented hosted trial':'Run the selected local agent';
 $('#runtime-note').textContent=hosted?'Tool execution stays in local Docker. Model calls go to Token Factory. A started trial cannot be retried or overwritten.':'Uses the cached local model and networkless Docker. No hosted model or Nebius runtime call. Each seed is a repeated agent attempt, not a distinct person. A started trial cannot be retried or overwritten.';
 const box=$('#sponsor-details');box.replaceChildren();
 if(!hosted)return;
 if(!data.allowSponsor)node('p','Hosted execution is disabled for this workspace. Preview is available; starting requires --allow-sponsor.',box);
 if(!p){node('p','No hosted preview yet. No provider request has been made by this preview flow.',box);return;}
 node('h4','Preview only · provider access unverified',box);
 node('p',p.model+' · '+p.endpoint,box);node('p',p.denominator.episodes+' planned episodes · at most '+p.budget.max_model_calls+' model calls',box);
 node('p',p.budget.cost_status,box);node('p','Sent to the model: task, documentation and shell output. Selected source, fixtures and image contents can be exposed through commands.',box);detail('Full data exposure and key handling',p.exposure,box);
 node('p','Local readiness at preview: '+(gate.status==='ready_to_call'?'checks passed; provider access remains unverified':'blocked')+(gate.issues.length?' · '+gate.issues.join('; '):'')+'. Starting rechecks this preview.',box);
 detail('Exact preview identity, image and call limits',{sha256:p.sha256,image:p.image,image_identity:p.image_identity,budget:p.budget,evaluator_preflight:p.evaluator_preflight},box);
 if(p.image_review)detail('Reviewed image changes',{summary:p.image_review.proposal?.summary,provider_exposure:p.image_review.proposal?.provider_exposure,reviewed_digest:p.image_review.reviewed_digest},box);
}
$('#sponsor-consent').onchange=()=>{if(current)$('#start').disabled=!canStart(current);};
$('#sponsor-image-review').oninput=()=>{$('#sponsor-consent').checked=false;if(current){current.sponsor=null;showSponsor(current);$('#start').disabled=true;}};
$('#sponsor-preview').onclick=async()=>{try{$('#sponsor-consent').checked=false;$('#sponsor-preview').disabled=true;const d=await api('tool/sponsor-preview',{id:current.id,expected:current.contract.sha256,imageReviewPath:$('#sponsor-image-review').value});show(d);}catch(e){error(e);}finally{$('#sponsor-preview').disabled=false;}};

function showProtocol(data){
 const p=data.decision_protocol;$('#decision-protocol').hidden=!p;if(!p)return;
 const box=$('#protocol-summary');box.replaceChildren();node('p',p.origin==='existing_evidence_demo'?'Existing-evidence demonstration. These outcomes and forecasts may already have been seen.':'Protocol enrolled before execution. This records local ordering, not trusted blinding.',box);
 node('p',p.scope,box);for(const stage of ['initial','eval_only','forecast_informed']){const row=p.rows.find(r=>r.stage===stage);node('p',({'initial':'Frozen initial','eval_only':'After direct agent eval only','forecast_informed':'After forecast reveal'}[stage])+': '+(row?choiceLabel(row.choice):'Not recorded'),box);}
 if(p.decision_changed!==null)node('p',p.decision_changed?'Decision changed after reveal. This is an observation, not evidence of improvement or causation.':'Decision unchanged after reveal. No improvement is established.',box);
 const ready=data.state.status==='complete';$('#protocol-form').hidden=!['eval_only','forecast_informed'].includes(p.next_stage);$('#protocol-save').disabled=!ready;$('#protocol-save').textContent=p.next_stage==='eval_only'?'Save eval-only choice':'Save forecast-informed choice';$('#protocol-reveal').hidden=p.next_stage!=='reveal';$('#protocol-choice').value='';$('#protocol-reason').value='';
 if(!ready)node('p','Wait for the full controller-checked direct agent result before recording the eval-only choice.',box);
 const history=$('#protocol-history');history.replaceChildren();for(const row of p.rows){const item=node('details','',history);node('summary',row.stage.replaceAll('_',' ')+' · '+new Date(row.at).toLocaleString(),item);if(row.reason)node('p',row.reason,item);detail('Exact stage and evidence binding',row,item);}
}
async function saveProtocol(stage,choice,reason){const p=current.decision_protocol;const data=await api('tool/decision-stage',{id:current.id,expected:current.contract.sha256,state_sha256:current.state_sha256,revision:p.rows.length,stage,...(stage==='reveal'?{}:{choice,reason})});show(data);await saved();}
$('#protocol-form').onsubmit=async event=>{event.preventDefault();try{$('#protocol-save').disabled=true;await saveProtocol(current.decision_protocol.next_stage,$('#protocol-choice').value,$('#protocol-reason').value);}catch(e){error(e);$('#protocol-save').disabled=false;}};
$('#protocol-reveal').onclick=async()=>{try{$('#protocol-reveal').disabled=true;await saveProtocol('reveal');}catch(e){error(e);}finally{$('#protocol-reveal').disabled=false;}};


function mcpValue(label,value,parent){
 const d=node('details','',parent);node('summary',label,d);node('pre',value.text,d);
 if(value.omitted_characters)node('p',value.omitted_characters+' characters omitted from this view; full bytes remain in the private copy.',d).className='small';
}
function showMcp(data){
 clearTimeout(timer);current=data;$('#create-panel').open=false;
 for(const id of ['preview','results','release-review','forecast','journey','glance','decision-protocol'])$('#'+id).hidden=true;
 const box=$('#mcp-recorded');box.hidden=false;box.replaceChildren();const v=data.mcp,participant=v.mode==='participant';
 node('p','SYNTHETIC · LOCAL · READ-ONLY COPY',box).className='small';node('h2',data.import.label,box);
 node('p',v.scope,box);node('strong',v.flaw,box);
 node('h3',participant?v.accepted+'/'+v.denominator+' accepted submissions':v.denominator+' recorded protocol sessions',box);
 node('p',participant?'Every registered condition remains in the denominator, including null submissions and runtime failures.':'These sessions exercised a fixed call sequence. They do not measure agent task completion.',box);
 node('p','No builder decision or forecast result is attached. Copied local receipt integrity does not independently attest chronology.',box).className='small';
 if(v.task)mcpValue('Exact downstream task',v.task,box);
 const tracks=node('div','',box);tracks.className='path-tracks';
 for(const row of v.rows){
  const track=node('div','',tracks);track.className='path-track';
  const version=node('div','',track);version.className='path-stop';node('h3',{'base':'Baseline','candidate-off':'Candidate · flag off','candidate-on':'Candidate · Markdown'}[row.condition],version);node('code',row.commit.slice(0,8),version);node('span',row.features.length?row.features.join(', '):'No feature flag',version).className='stage';
  const calls=node('div','',track);calls.className='path-stop';node('strong',row.mcp_calls+(row.mcp_calls===1?' call':' calls'),calls).className='metric';node('span','Actual MCP calls',calls).className='stage';
  const model=node('div','',track);model.className='path-stop';node('strong',participant?row.model_calls+' calls':'Scripted',model).className='metric';node('span',participant?'Model requests':'No model ran',model).className='stage';
  const outcome=node('div','',track);outcome.className='path-stop';node('strong',participant?(row.completed?'1/1':'0/1'):row.status,outcome).className='metric';node('span',participant?'Accepted submission':'Protocol session',outcome).className='stage';if(row.checker_reason)node('span',row.checker_reason,outcome).className='stage';
 }
 const identity=node('details','',box);node('summary','Exact source, fixture and registration identities',identity);node('pre',JSON.stringify(v.identity,null,2),identity);
 for(const row of v.rows){
  const item=node('details','',box);node('summary',row.condition+' · '+row.status+' · inspect retained path',item);
  node('p',(row.initialized?'Initialized':'Initialization not recorded')+' · '+row.advertised_tools+' advertised tools · '+row.mcp_calls+' actual calls.',item);
  if(row.error)node('p',row.error,item);
  if(participant){if(row.finish_reasons.length)node('p','Returned finish reasons: '+row.finish_reasons.join(', '),item).className='small';mcpValue('Final submission (null means no valid submission)',row.submission,item);mcpValue('Independent checker result',row.checker,item);detail('Returned usage only; timeout usage may be unknown',row.usage,item);}
  for(const [index,call] of row.calls.entries()){const callView=node('details','',item);node('summary','Call '+(index+1)+' · '+call.status,callView);mcpValue('Tool and arguments',call.request,callView);mcpValue('Actual MCP response',call.result,callView);}
  if(row.omitted_calls)node('p',row.omitted_calls+' further calls omitted from this view.',item);
 }
 node('p','Readback limits: '+v.limits.calls_per_condition+' calls per condition; '+v.limits.display_characters_per_value+' characters per displayed value. Raw private receipts remain intact.',box).className='small';
}
$('#mcp-mode').onchange=()=>{$('#mcp-participant-inputs').hidden=$('#mcp-mode').value!=='participant';};
$('#mcp-import').onclick=async()=>{const button=$('#mcp-import');button.disabled=true;try{$('#error').textContent='';const data=await api('tool/mcp-import',{mode:$('#mcp-mode').value,path:$('#mcp-path').value,sessionPath:$('#mcp-session-path').value,registrationPath:$('#mcp-registration-path').value,label:$('#mcp-label').value});show(data);await saved();}catch(e){error(e);}finally{button.disabled=false;}};
