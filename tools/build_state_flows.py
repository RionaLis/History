#!/usr/bin/env python3
"""Build an editable draft state-successor graph from Wikidata P155/P156.

Auto edges are deliberately stored separately from entity cards. Human overrides
in data/state-flow-overrides.json are applied on the next run; remove an edge by
adding its generated id to `exclude`, or add a reviewed edge to `include`.
Shares are not inferred here: drawing code treats automatic branch weights as
provisional and divides them equally until an editor supplies weights.
"""
import json, os, re, time, urllib.parse, urllib.request, urllib.error
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX=os.path.join(ROOT,'data','index.json')
OUT=os.path.join(ROOT,'data','state-flows.json')
OVERRIDES=os.path.join(ROOT,'data','state-flow-overrides.json')
API='https://www.wikidata.org/w/api.php'

def fetch(ids):
 params={'action':'wbgetentities','ids':'|'.join(ids),'props':'claims','format':'json'}
 req=urllib.request.Request(API+'?'+urllib.parse.urlencode(params),headers={'User-Agent':'HistoryChronology/1.0 (state-flow graph; local project)'})
 for attempt in range(5):
  try:
   with urllib.request.urlopen(req,timeout=45) as r:return json.load(r).get('entities',{})
  except urllib.error.HTTPError as ex:
   if ex.code != 429 or attempt == 4: raise
   delay=max(12,int(ex.headers.get('Retry-After','12')))
   print(f'Wikidata rate limit; retry in {delay}s',flush=True);time.sleep(delay)

def targets(entity, prop):
 out=[]
 for claim in entity.get('claims',{}).get(prop,[]):
  dv=claim.get('mainsnak',{}).get('datavalue',{}).get('value',{})
  q=dv.get('id')
  if q:out.append(q)
 return sorted(set(out))

def main():
 idx=json.load(open(INDEX,encoding='utf8'))
 ent={e['id']:e for e in idx['entities'] if e.get('type') in ('state','empire')}
 q_to_ids={}
 for e in ent.values():
  q=e.get('wikidata')
  if q:q_to_ids.setdefault(q,[]).append(e['id'])
 qids=sorted(q_to_ids)
 cache_path=os.path.join(ROOT,'data','state-wikidata-claims-cache.json')
 try:claims=json.load(open(cache_path,encoding='utf8'))
 except Exception:claims={}
 missing=[q for q in qids if q not in claims]
 for i in range(0,len(missing),50):
  batch=missing[i:i+50]
  try:
   fetched=fetch(batch)
   for q,item in fetched.items():
    src=item.get('claims',{})
    claims[q]={'claims':{p:src.get(p,[]) for p in ('P155','P156') if src.get(p)}}
   json.dump(claims,open(cache_path,'w',encoding='utf8'),ensure_ascii=False,separators=(',',':'))
  except Exception as ex:print('WARN Wikidata batch',i,repr(ex))
  if i+50<len(missing):time.sleep(1.1)
 edges={}
 for q,ids in q_to_ids.items():
  item=claims.get(q,{})
  pairs=[]
  pairs += [(p,q) for p in targets(item,'P155')]
  pairs += [(q,p) for p in targets(item,'P156')]
  for prev,cur in pairs:
   if prev not in q_to_ids or cur not in q_to_ids or prev==cur:continue
   for a in q_to_ids[prev]:
    for b in q_to_ids[cur]:
     ea,eb=ent[a],ent[b]
     if ea['end'] < -4000 or eb['start'] > 2000:continue
     common=set(ea.get('regions',[])) & set(eb.get('regions',[]))
     if not common:continue
     # choose a representative shared macro-lane. Exact lane pair is refined below.
     lane_a=next((s['lane'] for s in ea.get('spans',[]) if s['lane'].split('_')[0] in common),None)
     lane_b=next((s['lane'] for s in eb.get('spans',[]) if s['lane'].split('_')[0] in common),None)
     if not lane_a or not lane_b:continue
     if abs(ea['end']-eb['start'])>80:continue
     from_year=max(-4000,min(ea['end'],2000))
     if eb['end'] < from_year:continue
     to_year=max(from_year,max(-4000,min(eb['start'],2000)))
     eid=f'{a}__{b}__{from_year}_{to_year}'
     edges[eid]={'id':eid,'source':a,'target':b,'sourceQ':prev,'targetQ':q,'year':from_year,'fromYear':from_year,'toYear':to_year,'sourceLane':lane_a,'targetLane':lane_b,'kind':'wikidata','confidence':'automatic-unweighted'}
 # apply manual override layer, authored as ordinary JSON
 try: overrides=json.load(open(OVERRIDES,encoding='utf8'))
 except FileNotFoundError: overrides={'exclude':[],'include':[]}
 for eid in overrides.get('exclude',[]):edges.pop(eid,None)
 manual=overrides.get('include',[])
 manual_pairs={(e.get('source'),e.get('target')) for e in manual}
 edges={eid:e for eid,e in edges.items() if (e.get('source'),e.get('target')) not in manual_pairs}
 for e in manual:edges[e['id']]=e
 arr=sorted(edges.values(),key=lambda e:(e['year'],e['source'],e['target']))
 json.dump({'source':'Wikidata P155/P156; automatic provisional graph','count':len(arr),'edges':arr,'manualOverrides':OVERRIDES.replace(ROOT+'/','')},open(OUT,'w',encoding='utf8'),ensure_ascii=False,indent=2)
 print(f'state candidates: {len(ent)}; Q IDs: {len(qids)}; Wikidata items fetched: {len(claims)}; draft successor edges: {len(arr)}; saved {OUT}')
 for e in arr:
  if any(s in (e['source']+' '+e['target']) for s in ['ohm_Q2277','ohm_Q42834','ohm_Q12544','ohm_Q172107','ohm_Q34266']):print(e)
if __name__=='__main__':main()
