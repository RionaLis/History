#!/usr/bin/env python3
"""Write calculated OHM footprints into entity MD (color + area_series + timeline spans).
Requires data/ohm-areas.json created by calculate_ohm_areas.py.
"""
import colorsys,json,os,re
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION_LANES={}
for fn in os.listdir(os.path.join(ROOT,'content','regions')):
 if not fn.endswith('.md'):continue
 text=open(os.path.join(ROOT,'content','regions',fn),encoding='utf8').read();raw=text.split('---',2)[1]
 rid=re.search(r'^id:\s*["\']?(\w+)',raw,re.M).group(1)
 laneids=re.findall(r'"id"\s*:\s*"([\w_]+)"',raw)
 REGION_LANES[rid]=laneids
KEYWORDS={
'eu_ita':'итал грец греци афин спарт рим римск сици неапол македон эпир визант константинополь',
'eu_gal':'галл франц испан португал ибери каталон баск аквитан бургунд',
'eu_nor':'британ англ шотланд ирланд уэльс скандинав дан швед норвеж финлянд iceland england britain',
'eu_est':'росс русск польск украин белорус литов чех словак серб болгар румын венгр молдав варшавск',
'eu_sib':'сибир якут тувин бурят ханты манси',
'sw_egy':'египет нубий египт', 'sw_mgr':'магриб марокк алжир тунис мавритан сахара',
'sw_lev':'арав левант израиль иудей палест сирий', 'sw_mes':'месопотам вавилон ассир шумер ирак',
'sw_irn':'иран персид перс парфян сасанид', 'sw_ana':'анатол армян грузин осман турц',
'af_ne':'эфиоп нубий куш аксум судан сомал', 'af_we':'гана мали сонгай нигер бенин йоруб ашанти',
'af_ce':'конго руанда буганда карфаг', 'af_se':'зимбабве зулу бушмен мономотапа',
'in_nw':'инд синд пенджаб гандхар', 'in_gan':'ганг дели магадха маурья', 'in_eas':'бенгал ассам',
'in_dec':'декан марата', 'in_sth':'тамил чола пандья ланка цейлон',
'ea_sea':'вьетнам кхмер чам тай сиам бирма лаос малай', 'ea_mkj':'япон коре маньчжур',
'ea_ncn':'монгол юань северн кита', 'ea_scn':'южн кита мин нан', 'ea_tib':'тибет', 'ea_cas':'тюрк уйгур согд хорезм',
'oc_aus':'австрал', 'oc_mel':'папуа меланез', 'oc_nus':'индонез малай нусант яван', 'oc_pol':'полинез микронез гавай маори',
'na_mex':'мексик майя ацтек ольмек тлашкала', 'na_arc':'инуит эским арктик',
'na_pnw':'калифорн каскад салиш', 'na_swt':'пуэбло хопи навахо', 'na_mis':'мисиссип восточн ирокез чероки',
'sa_car':'майя ацтек мезоамерик кариб', 'sa_and':'инк кечуа анд', 'sa_amz':'амазон ориноко', 'sa_con':'аргентин чили уругвай парагвай патагон',
}
def lane_for(region,name,bbox=None):
 ids=REGION_LANES.get(region,[]); text=(name or '').lower()
 for lane in ids:
  keys=KEYWORDS.get(lane,'').split()
  if any(k in text for k in keys):return lane
 # Approximate sub-region from the OHM relation bounding-box center.
 # Region-level routing remains exact from MD; these thresholds only pick a lane.
 if bbox:
  lat=(bbox['minlat']+bbox['maxlat'])/2; lon=(bbox['minlon']+bbox['maxlon'])/2
  if region=='eu':
   return 'eu_sib' if lon>60 else 'eu_nor' if lat>56 or lon< -7 else 'eu_ita' if lat<45 and lon<25 else 'eu_gal' if lon<5 and lat<47 else 'eu_est' if lon>25 else 'eu_cen'
  if region=='sw':
   return 'sw_egy' if 20<=lon<38 and lat<33 else 'sw_mgr' if lon<15 and lat<38 else 'sw_mes' if 38<=lon<51 and 27<=lat<40 else 'sw_irn' if lon>=45 and lat<43 else 'sw_lev' if 32<=lon<40 else 'sw_ana'
  if region=='af':
   return 'af_ne' if lon>=30 and lat>=-8 else 'af_we' if lon<10 and lat>=-5 else 'af_se' if lat< -10 or lon>42 and lat<0 else 'af_ce'
  if region=='in':
   return 'in_sth' if lat<10 else 'in_dec' if lat<23 else 'in_nw' if lon<75 else 'in_eas' if lon>88 else 'in_gan'
  if region=='ea':
   return 'ea_sea' if lat<25 and lon<125 else 'ea_mkj' if lon>125 and lat>30 else 'ea_tib' if lat>35 and lon<105 else 'ea_ncn' if lat>=35 else 'ea_scn'
  if region=='na':
   return 'na_arc' if lat>58 else 'na_mex' if lat<32 and lon< -85 else 'na_swt' if lon< -105 and lat<42 else 'na_pnw' if lon< -110 else 'na_mis'
  if region=='sa':
   return 'sa_car' if lat>8 else 'sa_con' if lat< -15 else 'sa_and' if lon< -68 else 'sa_amz'
  if region=='oc':
   return 'oc_aus' if lat< -10 and 110<lon<160 else 'oc_nus' if 95<lon<140 and -12<lat<10 else 'oc_mel' if lon<160 and lat<0 else 'oc_pol'
 return ids[0] if ids else None

def parse_md(path):
 s=open(path,encoding='utf8').read();end=s.find('\n---',3)
 return s[3:end],s[end+4:]
def color(name):
 h=5381
 for ch in (name or ''): h=((h<<5)+h+ord(ch))&0xffffffff
 hue=h%360; light=68+(h>>8)%10
 r,g,b=colorsys.hls_to_rgb(hue/360,light/100,.44)
 return '#%02x%02x%02x'%(round(r*255),round(g*255),round(b*255))
def main():
 data=json.load(open(os.path.join(ROOT,'data','ohm-areas.json'),encoding='utf8'))['objects']; done=0; missing=[]
 for obj in data:
  path=os.path.join(ROOT,obj['path']);raw,body=parse_md(path)
  area=obj.get('area_km2'); region=obj.get('region'); name=obj.get('name',''); lane=lane_for(region,name,obj.get('bbox'))
  if not lane: continue
  if area is None:
   missing.append(obj['id']); continue
  start=obj.get('start');end=obj.get('end') or 2000
  if start is None: continue
  if end<=start:end=start+1
  raw=re.sub(r'^start:.*$',f'start: {start}',raw,flags=re.M)
  raw=re.sub(r'^end:.*$',f'end: {end}',raw,flags=re.M)
  # constant mapped footprint during this relation's OHM validity interval
  # Rebased to sqrt area / largest footprint for the same macro-region.
  raw= re.sub(r'^spans:.*?(?=^\w[\w-]*:|\Z)','',raw,flags=re.M|re.S)
  raw=re.sub(r'^area_series:.*?(?=^\w[\w-]*:|\Z)','',raw,flags=re.M|re.S)
  raw=re.sub(r'^area_source:.*?\n','',raw,flags=re.M)
  raw=re.sub(r'^color:.*?\n','',raw,flags=re.M)
  area_series=[{'year':start,'area_km2':area},{'year':end,'area_km2':area}]
  # Weight is absolute by regional max; the chart stacks/normalizes contemporaneous entities.
  max_reg=max((x.get('area_km2') or 0 for x in data if x.get('region')==region),default=area) or area
  share=max(.012,min(.72,.72*(area/max_reg)**.5))
  colorhex=color(obj.get('name_ohm') or obj.get('id'))
  add='\n'.join([
   f'color: "{colorhex}"',
   f'area_source: "OHM relation {obj["ohm_id"]}; '+('minimum display fallback' if obj.get('status')=='minimum_fallback' else 'bounding-box approximation' if obj.get('status')=='bbox_estimate' else 'spherical area, outer rings minus inner rings')+'"',
   'area_series: '+json.dumps(area_series,ensure_ascii=False,separators=(',',':')),
   'spans:',f'  - lane: "{lane}"',f'    points: [[{start},{share:.5f}],[{end},{share:.5f}]]'])
  raw=raw.rstrip()+'\n'+add+'\n'
  def fmt_year(y): return f'{abs(y)} до н.э.' if y <= 0 else f'{y} н.э.'
  period=f'| **Период** | {fmt_year(start)} — {fmt_year(end)} |'
  body=re.sub(r'^\| \*\*Период\*\* \|.*?\|$',period,body,flags=re.M)
  raw=raw.strip('\n')+'\n'
  with open(path,'w',encoding='utf8') as f:f.write('---\n'+raw+'---'+body)
  done+=1
 print(f'Обновлено карточек: {done}; без геометрии/площади: {len(missing)}')
 if missing:
  print('Нет площади:',', '.join(missing[:40]))
if __name__=='__main__':main()
