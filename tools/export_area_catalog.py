#!/usr/bin/env python3
"""Export OHM entities and calculated area metadata for the in-site editor."""
import json, os, re
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
area_path=os.path.join(ROOT,'data','ohm-areas.json')
areas={}
if os.path.exists(area_path):
 for item in json.load(open(area_path,encoding='utf-8')).get('objects',[]):areas[item['id']]=item
items=[]
for base,_,files in os.walk(os.path.join(ROOT,'content','entities')):
 for fn in sorted(files):
  if not fn.endswith('.md'): continue
  path=os.path.join(base,fn); text=open(path,encoding='utf-8').read()
  if not text.startswith('---'): continue
  end=text.find('\n---',3)
  if end<0: continue
  raw=text[3:end]
  def val(k):
   m=re.search(r'^'+re.escape(k)+r':\s*(.*?)\s*$',raw,re.M)
   if not m:return ''
   return m.group(1).strip().strip('"\'')
  if not val('ohm_id'): continue
  aid=val('id'); ar=areas.get(aid,{})
  lane_m=re.search(r'^\s*- lane:\s*["\']?([\w_]+)',raw,re.M)
  color_m=re.search(r'^color:\s*["\']?(#[0-9a-fA-F]{6})',raw,re.M)
  items.append({'id':aid,'name':val('name'),'label':val('label'),'name_ohm':val('name_ohm'),'ohm_id':val('ohm_id'),'wikidata':val('wikidata'),'region':val('region'),'lane':lane_m.group(1) if lane_m else '', 'color':color_m.group(1) if color_m else '', 'area_km2':ar.get('area_km2'),'area_status':ar.get('status'),'start':int(val('start')) if val('start').lstrip('-').isdigit() else ar.get('start'),'end':int(val('end')) if val('end').lstrip('-').isdigit() else ar.get('end'),'path':os.path.relpath(path,ROOT).replace(os.sep,'/')})
items.sort(key=lambda x:(x['region'],x['name']))
out=os.path.join(ROOT,'data','area-tool-entities.json')
with open(out,'w',encoding='utf8') as f:json.dump(items,f,ensure_ascii=False,indent=2)
print(f'{len(items)} объектов: {os.path.relpath(out,ROOT)}')
