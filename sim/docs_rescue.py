"""Explicit public official-docs retrieval after an in-app reading stop.

Search evidence is separate from browser completion. No private page text is sent.
"""
from urllib.parse import urlsplit
import re
from sim.adapters import tavily

def rescue(question, domains, *, receipts_path=None, response_path=None):
    if not domains or len(domains) > 3 or any(not re.fullmatch(r'[a-z0-9.-]+',d) or '.' not in d for d in domains):
        raise ValueError('Declare up to three official public documentation domains.')
    results = tavily.search(question, max_results=3, domains=domains,
                            receipts_path=receipts_path, response_path=response_path)
    accepted=[]; rejected=[]
    for c in results:
        u=urlsplit(c.url)
        if u.scheme!='https' or u.username or u.password or u.hostname not in domains:
            rejected.append(c.url)
        else: accepted.append({'url':c.url,'title':c.title,'excerpt':c.excerpt})
    return {'label':'RUNTIME','question':question,'official_domains':domains,
            'sources':accepted,'rejected_urls':rejected,'task_completion':'not assessed',
            'note':'Sources to inspect, not a resolved browser task or independent truth.'}

if __name__=='__main__':
    import argparse,json
    from pathlib import Path
    p=argparse.ArgumentParser(description='Public official-docs rescue; Basic Search costs one credit.')
    p.add_argument('question');p.add_argument('--domain',action='append',required=True)
    p.add_argument('--receipt-dir',required=True);p.add_argument('--allow-paid',action='store_true')
    a=p.parse_args()
    if not a.allow_paid:p.error('Print cost first, then explicitly pass --allow-paid. Planning estimate USD0.008; actual allowance/invoice unknown.')
    out=Path(a.receipt_dir);out.mkdir(parents=True,exist_ok=True)
    result=rescue(a.question,a.domain,receipts_path=out/'receipts.jsonl',response_path=out/'response.json')
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
