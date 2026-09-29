import json,pathlib,decimal,hashlib,collections,math
D=decimal.Decimal
root=pathlib.Path(__file__).resolve().parent
files={'pr':root/'ci-pr-qualified/ga73-pr-pilot.json','bugs':root/'ci-default-bugs/ga73-default-bugs.json'}
out={}
for kind,p in files.items():
 x=json.loads(p.read_text());rows=x.get('results') or x.get('bug_results');assert x['collection_qualified']
 assert len({(r.get('base'),r.get('head')) for r in rows})==len(rows) if kind=='pr' else True
 bills=[r['provider_billing'] for r in rows if r['model_requests']>0]
 assert all(b['provider_billing_complete'] and b['provider_paid_with']==['credits'] for b in bills)
 eur=sum((D(b['provider_credit_debit_eur']) for b in bills),D(0));usd=eur*D(x['fx_usd_per_eur'])
 # Independent string-to-integer scaled summation of all nonnegative credits.
 vals=[b['provider_credit_debit_eur'] for b in bills];scale=max(len(v.partition('.')[2]) for v in vals)
 scaled=sum(int(v.replace('.',''))*10**(scale-len(v.partition('.')[2])) for v in vals)
 assert D(scaled).scaleb(-scale)==eur
 d={'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows':len(rows),'measured':len(bills),'responses':sum(r['model_requests'] for r in rows),'eur':str(eur),'usd':str(usd),'usd_per_attempted':str(usd/D(len(rows))),'qualified':True}
 if kind=='pr':
  assert len(rows)==40 and all(r['diff_status']=='ok' for r in rows)
  proofs=x['no_call_proofs'];assert len(proofs)==20 and all(not r['model_request_attempts'] and not r['model_requests'] and not r['reported'] for r in proofs)
  assert all(r['diff_status']=='no_python_in_diff' for r in proofs[:5])
  assert all(r['diff_status'] in ['below_risk_threshold','no_targets_after_ranking'] for r in proofs[5:])
  d.update(reported_prs=sum(r['reported']>0 for r in rows),reports=sum(r['reported'] for r in rows),no_call_proofs=len(proofs),rule_of_three_upper_95=3/len(rows),exact_binomial_upper_95=1-.05**(1/len(rows)),conditional_rank_eligibility=40/55)
  assert d['reports']==0 and len(x['manifest']['python_sampling_frame'])==55
 else:
  print('Bug row fields',sorted(rows[0]))
  d['mechanically_caught']=sum(any(t['disposition']=='catching' for t in r.get('telemetry',[])) for r in rows)
  d['reported_bugs']=sum(bool(r.get('reported',r.get('reportable',False))) for r in rows)
  print('Bug report flag sample',{k:v for k,v in rows[0].items() if k in ['caught','reported','reported_catches','reportable','findings','surfaced']})
 out[kind]=d
out['scope']='Frozen historical bugs plus conditional default-risk-eligible settled Click PRs; not global recall/FPR, not independent human labels or wallet reconciliation.'
out['comparison_plan']={'disposition':'prose','reason':'Three release-gate headline measurements across incompatible populations; a shared chart would imply comparable denominators.'}
(root/'ga73-final-audit.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
