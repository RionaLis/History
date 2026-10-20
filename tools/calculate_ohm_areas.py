#!/usr/bin/env python3
"""Fetch OHM relation geometries and calculate geodesic areas, with resumable cache.

Usage: python3 tools/calculate_ohm_areas.py [--batch 8]
This calculates the relation's mapped footprint from outer and inner rings,
using a spherical geodesic approximation (mean Earth radius 6,371,008.8 m).
"""
import argparse, json, math, os, re, time, urllib.parse, urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE=os.path.join(ROOT,'data','ohm-area-cache.json')
OUT=os.path.join(ROOT,'data','ohm-areas.json')

def front(path):
 s=open(path,encoding='utf8').read(); raw=s.split('---',2)[1] if s.startswith('---') else ''
 d={}
 for line in raw.splitlines():
  m=re.match(r'^([\w-]+):\s*(.*?)\s*$',line)
  if m:d[m.group(1)]=m.group(2).strip().strip('"\'')
 return d

def area_ring(g):
 if len(g)<4 or (g[0]['lat']!=g[-1]['lat'] or g[0]['lon']!=g[-1]['lon']): return None
 R=6371008.8; s=0
 for a,b in zip(g,g[1:]):
  s+=math.radians(b['lon']-a['lon'])*(2+math.sin(math.radians(a['lat']))+math.sin(math.radians(b['lat'])))
 return abs(s*R*R/2)

def geometry_area(el):
 # Multipolygon boundaries are usually split into open ways. Stitch fragments
 # by exact endpoint coordinates before computing ring area.
 byrole={}; missing=0
 for m in el.get('members',[]):
  if m.get('type')!='way': continue
  g=m.get('geometry',[])
  if len(g)>=2: byrole.setdefault(m.get('role','outer'),[]).append(g)
 total=0; ring_count=0
 for role,paths in byrole.items():
  paths=[p[:] for p in paths]
  while paths:
   chain=paths.pop(0); changed=True
   while changed and (chain[0]['lat']!=chain[-1]['lat'] or chain[0]['lon']!=chain[-1]['lon']):
    changed=False
    for i,p in enumerate(paths):
     if chain[-1]==p[0]: chain.extend(p[1:])
     elif chain[-1]==p[-1]: chain.extend(list(reversed(p[:-1])))
     elif chain[0]==p[-1]: chain=list(p[:-1])+chain
     elif chain[0]==p[0]: chain=list(reversed(p[1:]))+chain
     else: continue
     paths.pop(i);changed=True;break
   a=area_ring(chain)
   if a is None: missing+=1;continue
   total+=a*(-1 if role=='inner' else 1);ring_count+=1
 if not ring_count:return None,missing
 return max(0,total),missing

def ohm_year(value):
 if value is None:return None
 m=re.match(r'^(-?\d+)',str(value).strip())
 return int(m.group(1)) if m else None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--batch',type=int,default=6);ap.add_argument('--pause',type=float,default=1.2);args=ap.parse_args()
 paths=[]
 for base,_,files in os.walk(os.path.join(ROOT,'content','entities')):
  for fn in files:
   if fn.endswith('.md'):
    p=os.path.join(base,fn);d=front(p)
    if d.get('ohm_id','').isdigit():paths.append((d,os.path.relpath(p,ROOT).replace(os.sep,'/')))
 paths.sort(key=lambda x:int(x[0]['ohm_id']))
 try: cache=json.load(open(CACHE,encoding='utf8'))
 except Exception:cache={}
 ids=sorted({int(d['ohm_id']) for d,p in paths if str(d['ohm_id']) not in cache or cache[str(d['ohm_id'])].get('status')=='no_closed_rings' or not cache[str(d['ohm_id'])].get('bbox')})
 print(f'{len(paths)} карточек; {len(cache)} из кеша; {len(ids)} осталось',flush=True)
 endpoint='https://overpass-api.openhistoricalmap.org/api/interpreter'
 for ix in range(0,len(ids),args.batch):
  group=ids[ix:ix+args.batch]; query='[out:json][timeout:90];('+''.join(f'relation({i});' for i in group)+');out geom;'
  data=urllib.parse.urlencode({'data':query}).encode(); last=None
  for attempt in range(5):
   try:
    req=urllib.request.Request(endpoint,data=data,headers={'User-Agent':'HistoryChronologyAreaTool/1.0 (open historical research)'})
    with urllib.request.urlopen(req,timeout=120) as resp: payload=json.load(resp)
    byid={str(e['id']):e for e in payload.get('elements',[]) if e.get('type')=='relation'}
    for ident in group:
     el=byid.get(str(ident))
     if el:
      a,missing=geometry_area(el); tags=el.get('tags',{}); status='ok'
      # If OHM has no stitchable rings, use the element bbox as a clearly
      # marked fallback footprint so the entity remains visible in the chart.
      if a is None and el.get('bounds'):
       b=el['bounds']; R=6371008.8
       a=R*R*math.radians(b['maxlon']-b['minlon'])*(math.sin(math.radians(b['maxlat']))-math.sin(math.radians(b['minlat'])))
       a=max(0,a);status='bbox_estimate'
      elif a is None: status='no_closed_rings'
      cache[str(ident)]={'ohm_id':ident,'area_m2':round(a,1) if a is not None else None,'area_km2':round(a/1e6,3) if a is not None else None,'start_date':tags.get('start_date'),'end_date':tags.get('end_date'),'name_ohm':tags.get('name'),'outer_inner_rings':sum(1 for m in el.get('members',[]) if m.get('role') in ('outer','inner') and m.get('type')=='way'),'unclosed_rings':missing,'bbox':el.get('bounds'),'status':status}
     else: cache[str(ident)]={'ohm_id':ident,'area_m2':None,'area_km2':None,'status':'not_found'}
    tmp=CACHE+'.tmp';json.dump(cache,open(tmp,'w',encoding='utf8'),ensure_ascii=False);os.replace(tmp,CACHE)
    print(f'{min(ix+len(group),len(ids))}/{len(ids)} fetched',flush=True);last=None;break
   except Exception as e:
    last=e;time.sleep(min(45,4*(attempt+1)))
  if last: print(f'ERROR batch {group}: {last}',flush=True)
  time.sleep(args.pause)
 rows=[]
 for d,p in paths:
  a=cache.get(str(d['ohm_id']),{})
  if d.get('chronology_source'):
   # Preserve a documented historical interval (e.g. Wikidata inception/dissolution)
   # when the OHM relation is only a snapshot or a short geometry revision.
   start=int(d['start']) if d.get('start','').lstrip('-').isdigit() else None
   end=int(d['end']) if d.get('end','').lstrip('-').isdigit() else 2000
  else:
   start=ohm_year(a.get('start_date'))
   if start is None:start=int(d['start']) if d.get('start','').lstrip('-').isdigit() else None
   end=ohm_year(a.get('end_date'))
   if end is None:end=2000
  rows.append({'id':d.get('id'),'name':d.get('name'),'path':p,'region':d.get('region'),'start':start,'end':end,**a})
 rows.sort(key=lambda x:(x.get('region') or '',x.get('name') or ''))
 with open(OUT,'w',encoding='utf8') as f:json.dump({'method':'spherical geodesic polygon area; outer rings minus inner rings','earth_radius_m':6371008.8,'objects':rows},f,ensure_ascii=False,indent=2)
 found=sum(1 for r in rows if r.get('area_km2') is not None);print(f'Итог: {found}/{len(rows)} рассчитано; {OUT}',flush=True)
if __name__=='__main__':main()
