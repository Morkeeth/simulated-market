'use strict';
// Agent report for one app visit: every model call behind the human page, as recorded.
(async()=>{
 const id=new URLSearchParams(location.search).get('visit');if(!id)return;
 const token=sessionStorage.getItem('workspace-token')||'';
 const el=(t,text,parent,style)=>{const e=document.createElement(t);if(text!=null)e.textContent=text;if(style)e.style.cssText=style;if(parent)parent.append(e);return e;};
 const box=el('section',null,null,'border:2px solid currentColor;border-radius:12px;padding:20px;margin:0 0 28px;font:14px/1.5 system-ui,sans-serif');
 document.querySelector('main').prepend(box);
 const back=el('a','← Back to the visit',box);back.href='/tools?visit='+id;
 let r;try{const res=await fetch('/api/app-check/result/'+id,{headers:{'X-Workspace-Token':token}});r=await res.json();if(!res.ok)throw Error(r.error);}catch(e){el('p','This visit could not be opened: '+e.message,box);return;}
 const sp=r.spend||{};
 el('h2','Agent report: '+r.name,box,'margin:10px 0 4px');
 el('p',r.headline||'',box,'font-size:17px;margin:0 0 10px');
 el('p','Model: '+(sp.model||r.model||'none')+' on '+(sp.provider||'no provider')+'. '+(sp.model_calls||0)+' calls, run cap '+sp.max_calls+' calls. '+(sp.prompt_tokens||0)+' tokens in, '+(sp.completion_tokens||0)+' out. Listed-rate estimate USD '+Number(sp.listed_rate_estimate_usd||0).toFixed(6)+'. Held reservations USD '+Number(sp.held_reservation_usd||0).toFixed(4)+'. This is a list-price estimate, not an invoice.',box);
 el('p','How a step works: the model, as the visitor, reads the screen and says whether its task is completed there, pointing at words that must really be on the screen. A second model call then gets only the task, the ordered steps and the text of that screen, and must agree. A plain rule then checks the steps show every part the task names. Otherwise the model picks the next move. The browser refuses every request that is not a plain read. Blocked requests in this run: '+((r.raw||{}).blocked_write_requests||[]).length+'.',box);
 if(r.control_result)el('p','Control: must fail '+r.control_result.must_fail.join(', ')+'. Failed as planted: '+(r.control_result.failed_as_planted.join(', ')||'none')+'. Control held: '+r.control_result.held+'.',box,'font-weight:700');
 if(r.job)el('p','Task given to four visitors: '+r.job.text+'. Source: '+r.job.source+'.'+(r.cache_key?' Saved-result key: '+r.cache_key+' (address, task, visitor goals, tries, model, step limits).':''),box);
 if(r.counts)el('p','Over '+r.counts.sessions+' visits: said done '+r.counts.claimed+', screen confirmed '+r.counts.screen_confirmed+', job completed '+r.counts.confirmed+'.',box,'font-weight:700');
 (r.tries||[]).forEach((rows,ti)=>{el('h3','Try '+(ti+1),box,'margin:14px 0 4px');for(const v of rows){
  const d=el('details',null,box,'border-top:1px solid;padding:8px 0');el('summary',v.name+' · '+(v.outcome||v.status)+' · '+v.steps.length+' steps · goal: '+v.goal,d,'cursor:pointer;font-weight:700');
  if(v.reason)el('p',v.reason,d);
  for(const s of v.steps){const p=el('div',null,d,'margin:8px 0 8px 14px;padding-left:10px;border-left:3px solid');
   el('div','Step '+s.order+' · '+s.status+' · '+s.url,p,'font-weight:700');
   const l=s.look;if(l)el('div','First call, the visitor ('+(l.model_ms||0)+' ms, '+((l.usage||{}).prompt_tokens||0)+' in / '+((l.usage||{}).completion_tokens||0)+' out): done here='+l.found+', words on page='+l.on_page+(l.quote?', pointed at: "'+l.quote.replace(/\s+/g,' ').slice(0,200)+'"':''),p);
   if(s.claim)el('div','Second call, steps and screen text only ('+((s.confirm_call||{}).model_ms||0)+' ms): '+(s.claim.confirmed?'agreed':'did not agree')+'. '+s.claim.why+' State: '+((s.claim_state||{}).state||'')+((s.claim_state||{}).missing||[]).map(m=>' missing '+m).join(''),p);
   if(s.model_reply)el('pre','Move ('+(s.model_ms||0)+' ms, '+((s.usage||{}).prompt_tokens||0)+' in / '+((s.usage||{}).completion_tokens||0)+' out): '+s.model_reply.replace(/\s+/g,' '),p,'white-space:pre-wrap;overflow-wrap:anywhere;margin:2px 0;font-size:12px');
   if(s.reason)el('div',s.reason,p);}
 }});
 const d=el('details',null,box,'border-top:1px solid;padding:8px 0');el('summary','Every model call in this run ('+(sp.calls||[]).length+')',d,'cursor:pointer;font-weight:700');
 const t=el('table',null,d,'border-collapse:collapse;font-size:12px;margin-top:6px');
 for(const c of [{call:'call',ms:'ms',usage:{prompt_tokens:'in',completion_tokens:'out'},accounted_usd:'USD est.',status:'status'},...(sp.calls||[])]){const tr=el('tr',null,t);for(const x of [c.call,c.ms,(c.usage||{}).prompt_tokens??'',(c.usage||{}).completion_tokens??'',typeof c.accounted_usd==='number'?c.accounted_usd.toFixed(8):c.accounted_usd,c.status])el('td',String(x),tr,'padding:2px 10px 2px 0;border-bottom:1px solid #8884');}
 el('p','Below this box is the larger experiment with the same model: recorded attempts on code changes.',box,'margin:10px 0 0');
})();
