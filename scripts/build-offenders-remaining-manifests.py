# ruff: noqa
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path
from collections import OrderedDict
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'fixtures/product-prototype'
CAT=ROOT/'.product-prototype/offenders-remaining-phase1/catalogs'
sys.path.insert(0,str(ROOT/'src'))
from tidy_orchestrator.artifacts import canonical_json_bytes, sha256_digest

REGISTERED={
'offenders-by-principal-offence-and-period','offenders-by-sex-principal-offence-and-period',
'offenders-by-principal-offence-age-and-period','offender-rates-by-principal-offence-age-and-period',
'offenders-by-sex-age-period-and-statistic'}
BOUNDED={
'workbooks/recorded-crime-offenders-2022-23-cube-4-source.xlsx':'workbooks/recorded-crime-offenders-2022-23-cube-4-remaining-bounded.xlsx',
'workbooks/recorded-crime-offenders-2023-24-cube-2-source.xlsx':'workbooks/recorded-crime-offenders-2023-24-cube-2-remaining-bounded.xlsx',
'workbooks/recorded-crime-offenders-2023-24-cube-3-source.xlsx':'workbooks/recorded-crime-offenders-2023-24-cube-3-remaining-bounded.xlsx',
'workbooks/recorded-crime-offenders-2024-25-cube-3-source.xlsx':'workbooks/recorded-crime-offenders-2024-25-cube-3-remaining-bounded.xlsx',
'workbooks/recorded-crime-offenders-2023-24-cube-7-source.xlsx':'workbooks/recorded-crime-offenders-2023-24-cube-7-remaining-bounded.xlsx',
'workbooks/recorded-crime-offenders-2024-25-cube-7-source.xlsx':'workbooks/recorded-crime-offenders-2024-25-cube-7-remaining-bounded.xlsx'}
parser=argparse.ArgumentParser()
parser.add_argument('--check',action='store_true')
parser.add_argument('--bootstrap-contracts',action='store_true',help='write bootstrap v1 contracts only when no v2 contract exists')
args=parser.parse_args()
mem=json.load(open(FIX/'offenders-release-family-membership-v1.json'))
families=OrderedDict((f['familyId'],f['members']) for f in mem['families'] if f['familyId'] not in REGISTERED)
if len(families)!=47 or sum(map(len,families.values()))!=170: raise RuntimeError('pending Offenders closure mismatch')
expected_outputs:set[Path]=set()
def emit(path:Path,data:bytes)->None:
 expected_outputs.add(path)
 if args.check:
  if not path.is_file() or path.read_bytes()!=data: raise RuntimeError(f'generated output drift: {path.relative_to(ROOT)}')
 else:
  temporary=path.with_suffix(path.suffix+'.tmp'); temporary.write_bytes(data); temporary.replace(path)

def catfile(m): return CAT/f"{m['releaseId']}-{m['downloadOrdinal']}-{m['physicalSheetName'].replace(' ','_')}.json"
def sample(c): return ' '.join(map(str,c.get('sample',[])))
def rows(c):
 out=[]
 for s in c['segments']:
  z=re.match(r'R(\d+)C',s)
  if z: out.append(int(z.group(1)))
 return out

def candidates(d,kind=None,pattern=None,all_pattern=False,min_row=5,max_row=None):
 out=[]
 for c in d['catalog']['candidates']:
  if kind and kind not in c['kinds']: continue
  rs=rows(c)
  if rs and (min(rs)<min_row or (max_row is not None and max(rs)>max_row)): continue
  vals=list(map(str,c.get('sample',[])))
  if pattern:
   matches=[bool(re.search(pattern,v,re.I)) for v in vals]
   if not matches or (not all(matches) if all_pattern else not any(matches)): continue
  out.append(c)
 return out

def ids(values): return [c['id'] for c in values]
def unique(values):
 seen=[]
 for value in values:
  if value not in seen: seen.append(value)
 return seen

def value_regions(d):
 for kind in ('all-observation-panels-trimmed-leading-label','all-observation-panels'):
  found=candidates(d,kind=kind,min_row=0)
  if found: return [max(found,key=lambda c:c['selectedCellCount'])['id']]
 panels=candidates(d,kind='observation-panel',min_row=5)
 if not panels: raise RuntimeError('no observation panel')
 return ids(panels)

def direct(d,pattern=None):
 return ids([c for c in candidates(d,kind='direct-row-projection-group',pattern=pattern,min_row=6) if all(re.match(r'R\d+C1(?::|$)',segment) for segment in c['segments'])])
def direct_without(d,pattern):
 return ids([c for c in candidates(d,kind='direct-row-projection-group',min_row=6) if all(re.match(r'R\d+C1(?::|$)',segment) for segment in c['segments']) and not re.search(pattern,sample(c),re.I)])
def top(d,pattern,*,all_pattern=False,min_row=5,max_row=8): return ids(candidates(d,kind='top-header-level-group',pattern=pattern,all_pattern=all_pattern,min_row=min_row,max_row=max_row))
def largest_top_row(d,pattern,max_row=8):
 found=candidates(d,kind='top-header-level-group',pattern=pattern,min_row=5,max_row=max_row)
 by_row={}
 for candidate in found:
  selected_rows=set(rows(candidate))
  if len(selected_rows)==1:
   row=next(iter(selected_rows)); by_row.setdefault(row,[]).append(candidate)
 if not by_row: return []
 target=max(by_row,key=lambda row:sum(item['selectedCellCount'] for item in by_row[row]))
 return ids(by_row[target])
def anchor(d,pattern): return ids(candidates(d,kind='preceding-panel-anchor-group',pattern=pattern,min_row=6))
def merged(d,pattern): return ids(candidates(d,kind='merged-header-anchor',pattern=pattern,min_row=5))
def fmt(d,pattern,seg=None):
 out=candidates(d,kind='format-header-group',pattern=pattern,min_row=5)
 if seg: out=[c for c in out if any(re.search(seg,s) for s in c['segments'])]
 return ids(out)
def years(d): return top(d,r'(?:19|20)\d\d\s*[–-]\s*\d\d',all_pattern=True,max_row=None)
def dims(entries): return [{'name':n.replace('_',' '),'memberRegions':unique(r),'direction':direction,'captionHints':[]} for n,r,direction in entries]
def dual(name,regions): return [(name,regions,'WNW')]

def map_for(fid,m,d):
 values=value_regions(d); ds=[]
 stat=lambda: top(d,r'Number|Offender rate|Proportion',max_row=None)
 juris_top=lambda: top(d,r'NSW|New South Wales|Vic\.?|Qld|Queensland|South Australia|Western Australia|Tas\.?|Northern Territory|\bACT\b|Capital Territory|Australia|\bAust\b',max_row=None)
 juris_anchor=lambda: anchor(d,r'New South Wales|Victoria|Queensland|South Australia|Western Australia|Tasmania|Northern Territory|Capital Territory|Australia')
 sex_anchor=lambda: anchor(d,r'Males|Females|Persons')
 sex_top=lambda: top(d,r'Males|Females|Persons',max_row=None)
 if fid=='offenders-by-principal-offence-and-jurisdiction-snapshot':
  period=years(d)+merged(d,r'(?:19|20)\d\d')
  ds=[('principal_offence',direct(d),'W'),('jurisdiction',juris_top(),'N'),('statistic_basis',stat(),'NNW')]+dual('observation_period',period)
 elif fid.startswith('offenders-by-sex-and-principal-offence-'):
  sex=sex_top()+sex_anchor()
  ds=[('principal_offence',direct(d),'W'),('observation_period',years(d),'N')]+dual('sex',sex)+[('statistic_basis',stat(),'NNW')]
 elif fid=='offenders-by-sex-age-and-jurisdiction-snapshot':
  period=years(d)+merged(d,r'(?:19|20)\d\d')
  ds=[('age_group',direct(d),'W'),('sex',sex_anchor(),'WNW'),('jurisdiction',juris_top(),'N'),('statistic_basis',stat(),'NNW')]+dual('observation_period',period)
 elif fid in {'offenders-by-sex-times-proceeded-and-jurisdiction-snapshot','youth-offenders-by-sex-and-repeat-proceedings-jurisdiction'}:
  period=years(d)+merged(d,r'(?:19|20)\d\d')
  ds=[('times_proceeded',direct(d),'W'),('sex',sex_anchor(),'WNW'),('jurisdiction',juris_top(),'N'),('statistic_basis',stat(),'NNW')]+dual('observation_period',period)
 elif fid=='offenders-by-age-times-proceeded-and-jurisdiction':
  values=ids(candidates(d,kind='repeated-observation-panels',min_row=7))[:1]
  jurisdiction=juris_top()+juris_anchor()
  ds=[('age_group',direct_without(d,r'="Age"'),'W'),('times_proceeded',largest_top_row(d,r'1|2|3|4|5 or more|Total|Mean',max_row=7),'N')]+dual('jurisdiction',jurisdiction)+[('statistic_basis',stat(),'NNW')]
 elif fid=='youth-offenders-by-principal-offence-and-period':
  ds=[('principal_offence',direct(d),'W'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='youth-offenders-by-sex-principal-offence-and-period':
  ds=[('principal_offence',direct(d),'W'),('observation_period',years(d),'N'),('sex',sex_top()+sex_anchor(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='youth-offenders-by-principal-offence-jurisdiction-and-period':
  ds=[('principal_offence',direct(d),'W'),('observation_period',years(d),'N'),('jurisdiction',juris_top()+juris_anchor(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='youth-offenders-by-sex-principal-offence-and-age-australia':
  ds=[('principal_offence',direct(d),'W'),('sex',sex_anchor(),'WNW'),('age_group',top(d,r'years|Youth offenders|All offenders',max_row=7),'N'),('statistic_basis',stat(),'WNW')]
 elif fid=='youth-offenders-by-principal-offence-age-and-jurisdiction':
  ds=[('principal_offence',direct(d),'W'),('age_group',top(d,r'years|Youth offenders|All offenders',max_row=7),'N'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='youth-offenders-by-age-sex-and-period-australia':
  ds=[('age_group',direct(d),'W'),('sex',sex_anchor()+sex_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='youth-offenders-by-sex-age-and-jurisdiction-snapshot':
  ds=[('age_group',direct(d),'W'),('sex',sex_anchor(),'WNW'),('jurisdiction',juris_top(),'N'),('statistic_basis',stat(),'NNW'),('observation_period',years(d)+merged(d,r'(?:19|20)\d\d'),'WNW')]
 elif fid=='youth-offenders-by-repeat-proceedings-age-and-jurisdiction':
  ds=[('times_proceeded',direct(d),'W'),('age_group',top(d,r'years|Youth offenders|All offenders',max_row=7),'N'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='offenders-by-indigenous-status-principal-offence-and-jurisdiction':
  ds=[('principal_offence',direct(d),'W'),('indigenous_status',anchor(d,r'Aboriginal|Non-Indigenous|Total'),'WNW'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='offender-rates-by-indigenous-status-rate-type-and-jurisdiction':
  ds=[('observation_period',direct(d),'W'),('jurisdiction',juris_top(),'NNW'),('indigenous_status',top(d,r'Aboriginal|Non-Indigenous|Ratio',max_row=7),'N'),('rate_basis',top(d,r'Crude rate|Age standardised rate',max_row=None)+anchor(d,r'Crude rate|Age standardised rate'),'WNW')]
 elif fid=='offenders-by-indigenous-status-sex-age-and-jurisdiction':
  ds=[('age_group',direct(d),'W'),('sex',sex_anchor(),'WNW'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'NNW'),('indigenous_status',top(d,r'Aboriginal|Non-Indigenous|Total',max_row=7),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='offenders-by-indigenous-status-repeat-proceedings-and-jurisdiction':
  ds=[('times_proceeded',direct(d),'W'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'NNW'),('indigenous_status',top(d,r'Aboriginal|Non-Indigenous|Total',max_row=7),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='offenders-police-proceedings-northern-territory':
  # The Northern Territory publication has no method-of-proceeding axis.
  ds=[('principal_offence',direct(d),'W'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid.startswith('offenders-police-proceedings-'):
  ds=[('principal_offence',direct(d),'W'),('method_of_proceeding',anchor(d,r'Court action|Non-court action|Total'),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-summary-characteristics':
  ds=[('characteristic_category',direct(d),'W'),('characteristic_group',anchor(d,r'Principal offence|Sex|Age|Times proceeded|Indigenous status|Total offenders'),'WNW'),('jurisdiction',juris_top(),'N'),('statistic_basis',top(d,r'Proportion of FDV|proportion of all offenders',max_row=45),'WNW')]
 elif fid=='fdv-principal-offence-by-sex-australia-time-series':
  ds=[('principal_offence',direct(d),'W'),('sex',sex_anchor()+sex_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-principal-offence-by-sex-and-age-australia':
  age_headers=largest_top_row(d,r'years|Total|Mean age|Median age',max_row=7)
  ds=[('principal_offence',direct(d),'W'),('sex',sex_anchor(),'WNW'),('age_group',age_headers,'N'),('statistic_basis',stat(),'WNW')]
 elif fid=='fdv-principal-offence-by-sex-jurisdiction-time-series':
  ds=[('principal_offence',direct(d),'W'),('sex',sex_anchor(),'WNW'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-selected-characteristics-by-sex-jurisdiction':
  ds=[('characteristic_category',direct(d),'W'),('characteristic_group',anchor(d,r'Age|Times proceeded|Total'),'WNW'),('sex',sex_top(),'N'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-indigenous-status-by-sex-jurisdiction-time-series':
  ds=[('sex',direct(d),'W'),('indigenous_status',anchor(d,r'Aboriginal|Non-Indigenous|Total'),'WNW'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-indigenous-status-by-sex-and-age-jurisdiction':
  ds=[('age_group',direct(d),'W'),('indigenous_status',anchor(d,r'Aboriginal|Non-Indigenous|Total'),'WNW'),('sex',sex_top(),'N'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-indigenous-status-by-principal-offence-and-sex-jurisdiction':
  ds=[('principal_offence',direct(d),'W'),('indigenous_status',anchor(d,r'Aboriginal|Non-Indigenous|Total'),'WNW'),('sex',sex_top(),'N'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-proceedings-by-principal-offence-method-jurisdiction-time-series':
  ds=[('principal_offence',direct(d),'W'),('method_of_proceeding',top(d,r'Court action|Non-court action|Total proceedings',max_row=6),'NNW'),('jurisdiction',juris_top(),'WNW'),('observation_period',years(d),'N')]
 elif fid=='fdv-breach-order-offenders-by-jurisdiction-time-series':
  ds=[('jurisdiction',direct(d),'W'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='fdv-breach-order-offenders-selected-characteristics-jurisdiction':
  ds=[('characteristic_category',direct(d),'W'),('characteristic_group',anchor(d,r'Age|Indigenous status|Total'),'WNW'),('sex',sex_top(),'N'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('statistic_basis',stat(),'NNW')]
 elif fid=='covid-offenders-by-age-and-sex-time-series':
  ds=[('age_group',direct(d),'W'),('sex',sex_anchor()+sex_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='covid-offenders-selected-characteristics-jurisdiction-time-series':
  ds=[('characteristic_category',direct(d),'W'),('characteristic_group',anchor(d,r'Sex|Age|Times proceeded|Total'),'WNW'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='covid-proceedings-by-method-jurisdiction-time-series':
  ds=[('method_of_proceeding',direct(d),'W'),('jurisdiction',juris_anchor()+juris_top(),'WNW'),('observation_period',years(d),'N'),('statistic_basis',stat(),'NNW')]
 elif fid=='offenders-by-preliminary-anzsoc-2023-principal-offence-and-jurisdiction':
  ds=[('principal_offence',direct(d),'W'),('jurisdiction',juris_top(),'N'),('classification_context',anchor(d,r'ANZSOC 2023'),'WNW')]
 else: raise KeyError(fid)
 clean=[]
 for name,regions,direction in ds:
  regions=unique(regions)
  if not regions: raise RuntimeError(f'no regions {fid} {m["releaseId"]} {name}')
  clean.append((name,regions,direction))
 return {'version':'semantic-table-map-v1','table':{'name':f'Recorded Crime — Offenders — {fid} — {m["releaseId"]}','values':{'name':'published value','regions':values},'dimensions':dims(clean)}}

def norm(value): return ' '.join(str(value).strip().split())
def code(value):
 raw=norm(value); slug=re.sub(r'[^A-Z0-9]+','_',raw.upper()).strip('_') or 'VALUE'; return slug[:80]+'_'+hashlib.sha256(raw.encode()).hexdigest()[:8]
def all_aliases(path):
 wb=openpyxl.load_workbook(path,data_only=False,read_only=False); out={}
 for ws in wb.worksheets:
  for cell in ws._cells.values():
   if cell.value is not None and not (isinstance(cell.value,str) and cell.value.startswith('=')):
    raw=norm(cell.value)
    if raw: out[raw]=code(raw)
 wb.close(); return out

plan={'schemaVersion':'tidy.offenders-remaining-semantic-map-plan/v1','recordedAt':'2026-08-25T12:00:00+00:00','acceptanceAuthority':False,'trainingEligibility':False,'families':[]}
for fid,members in families.items():
 work=[]; planned=[]; names=None
 for member in members:
  d=json.load(open(catfile(member))); mp=map_for(fid,member,d); mb=canonical_json_bytes(mp)+b'\n'
  year=int(member['releaseId'][:4]); replay=f"replay/recorded-crime-offenders-{member['cubeId']}-{member['tableNamespace']}-{member['physicalTableNumber']}-{year}.response.txt"
  emit(FIX/replay,mb); path=BOUNDED.get(member['sourcePath'],member['sourcePath']); data=(FIX/path).read_bytes()
  entry={'year':year,'referenceDate':f'{year+1}-06-30','path':path,'contentDigest':sha256_digest(data),'byteLength':len(data),'sheet':member['physicalSheetName'],'releaseId':member['releaseId'],'downloadOrdinal':member['downloadOrdinal'],'cubeId':member['cubeId'],'tableNamespace':member['tableNamespace'],'replayResponse':{'path':replay,'contentDigest':sha256_digest(mb),'byteLength':len(mb),'historicalModel':'human-authored/deterministic-geometry-v1','acceptanceAuthority':False}}
  if path!=member['sourcePath']: entry['normalization']='digest-pinned-bounded-offenders-remaining-v1'
  work.append(entry); planned.append({'releaseId':member['releaseId'],'downloadOrdinal':member['downloadOrdinal'],'cubeId':member['cubeId'],'tableNamespace':member['tableNamespace'],'physicalSheetName':member['physicalSheetName'],'sourcePath':member['sourcePath'],'sourceDigest':member['sourceDigest'],'executionPath':path,'executionDigest':entry['contentDigest'],'semanticMap':mp})
  current=[x['name'].replace(' ','_') for x in mp['table']['dimensions']]; names=names or current
  if names!=current: raise RuntimeError(f'dimension drift {fid}')
 cohort={'schemaVersion':'tidy.product-prototype-cohort/v1','cohortId':f'recorded-crime-offenders-{fid}','publicationId':'recorded-crime-offenders','tableFamilyId':fid,'generation':{'provider':'openai-codex','model':'openai-codex/gpt-5.6-luna','reasoning':'high','promptContract':'cell-role-semantic-map-v13-adjacent-year-aware','maximumCalls':2*len(work),'maximumCostUsd':2.0,'correctionPolicy':'one-pre-execution-compilation-correction-only'},'acceptanceContract':f'acceptance/recorded-crime-offenders-{fid}-v1.json','workerLimits':{'maxWarnings':100000},'workbooks':work}
 emit(FIX/f'recorded-crime-offenders-{fid}.json',(json.dumps(cohort,indent=2,ensure_ascii=False)+'\n').encode())
 aliases={name:{} for name in names}
 for entry in work:
  for raw,coded in all_aliases(FIX/entry['path']).items():
   for name in names: aliases[name][raw]=coded
 expected={'minimumRows':1,'maximumRows':100000,'sourceColumns':{'minimum':1,'maximum':200}}
 fields={'jurisdiction':'jurisdictions','indigenous_status':'indigenousStatuses','sex':'sexes','age_group':'ageGroups','principal_offence':'principalOffences','classification_context':'classificationContexts','statistic_basis':'statisticBases','rate_basis':'rateBases','characteristic_group':'characteristicGroups','characteristic_category':'characteristicCategories','observation_period':'observationPeriods','method_of_proceeding':'methodsOfProceeding','times_proceeded':'timesProceeded'}
 for name in names: expected[fields[name]]=sorted(set(aliases[name].values()))
 contract={'schemaVersion':'tidy.table-family-acceptance/v1','contractId':f'recorded-crime-offenders-{fid}-v1','tableFamilyId':fid,'measures':[{'id':'published-value','unitId':'published-unit','numeric':True,'minimum':0,'missingValues':{'n.a.':'not_applicable','na':'not_available','n.p.':'suppressed','np':'suppressed','..':'not_available'}}],'requiredDimensions':names,'dimensionHeaders':{name:[name.replace('_',' ')] for name in names},'aliases':aliases,'strictAliasMatching':True,'uniqueKey':['publication_vintage_date','reference_date']+[{'jurisdiction':'jurisdiction_id','indigenous_status':'indigenous_status_id','sex':'sex_id','age_group':'age_group_id','principal_offence':'principal_offence_id','classification_context':'classification_context_id','statistic_basis':'statistic_basis_id','rate_basis':'rate_basis_id','characteristic_group':'characteristic_group_id','characteristic_category':'characteristic_category_id','observation_period':'observation_period_id','method_of_proceeding':'method_of_proceeding_id','times_proceeded':'times_proceeded_id'}[name] for name in names]+['measure_id'],'expected':expected,'allowedExecutionWarnings':[],'totalEquations':[],'totalValidation':'not_applicable','automaticAcceptance':True,'trainingEligibility':False,'preservePublicationVintage':True,'preserveRawValueText':True}
 target=FIX/f'acceptance/recorded-crime-offenders-{fid}-v1.json'
 existing=json.loads(target.read_text()) if target.is_file() else None
 if existing is not None and existing.get('schemaVersion')=='tidy.table-family-acceptance/v2':
  if args.bootstrap_contracts: raise RuntimeError(f'refusing to regress finalized v2 contract: {target.name}')
 elif args.bootstrap_contracts or existing is None:
  emit(target,(json.dumps(contract,indent=2,ensure_ascii=False)+'\n').encode())
 elif args.check:
  emit(target,(json.dumps(contract,indent=2,ensure_ascii=False)+'\n').encode())
 else:
  raise RuntimeError(f'bootstrap contract requires --bootstrap-contracts: {target.name}')
 plan['families'].append({'familyId':fid,'members':planned})
emit(FIX/'offenders-remaining-semantic-map-plan-v1.json',(json.dumps(plan,indent=2,ensure_ascii=False)+'\n').encode())
contracts=set((FIX/'acceptance').glob('recorded-crime-offenders-*-v1.json'))
expected_contracts={FIX/'acceptance'/f'recorded-crime-offenders-{fid}-v1.json' for fid in families}
if expected_contracts-contracts: raise RuntimeError('missing remaining Offenders contract output')
if any(json.loads(path.read_text()).get('schemaVersion') not in {'tidy.table-family-acceptance/v1','tidy.table-family-acceptance/v2'} for path in expected_contracts): raise RuntimeError('unexpected remaining Offenders contract schema')
print(json.dumps({'families':len(families),'members':sum(map(len,families.values())),'checked':args.check,'bootstrapContracts':args.bootstrap_contracts}))
