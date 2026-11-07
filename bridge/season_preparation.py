"""Sequential, resumable season orchestration around the shared coordinator."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import time
import unicodedata

from .annotation_progress import atomic
from .diagnostics import safe_exception
from .preparation import AssetStore,annotations_complete,identity,prepare,read_json,validate_bundle,process_alive


def normalized(value):
    return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()).strip()


def matches(event,*names):
    return any(f' {normalized(alias)} ' in f' {normalized(name)} ' for alias in event['aliases'] for name in names)


def calendar(year):
    path=Path(__file__).parent/'data'/f'calendar-{year}.json'
    value=read_json(path)
    if value.get('schema')!='season-calendar-v1' or value.get('year')!=year:raise ValueError('Calendar schema/year mismatch')
    if len({e['id'] for e in value['events']})!=len(value['events']):raise ValueError('Duplicate calendar event')
    return value


def inventory(root,public,year):
    """Read-only: neither creates directories nor repairs invalid assets."""
    records=[]
    for pointer in sorted(Path(root).glob(f'circuit-*-{year}/current.json')):
        record={'asset':pointer.parent.name,'integrity':'invalid'}
        try:
            revision=read_json(pointer)['revision']
            if not re.fullmatch(r'[a-f0-9]{32}',revision):raise ValueError('Invalid revision')
            bundle=validate_bundle(read_json(pointer.parent/f'{revision}.json'))
            meta=bundle['identity']
            if meta['assetKey']!=pointer.parent.name or meta['year']!=year:raise ValueError('Store identity mismatch')
            record.update(identity=meta,integrity='valid',kind='dynamic',complete=annotations_complete(bundle),bundle=bundle,
                          calibration=bundle['calibration']['validation'],cornerCount=len((bundle.get('corners') or {}).get('corners',[])),sectorStatus='complete' if annotations_complete(bundle) else 'missing-or-partial',
                          checkpoints=len(list((pointer.parent/'annotations').glob('*.json'))))
        except Exception as exc:record['error']=safe_exception(exc,'cache')
        records.append(record)
    # The original Austin registry points at public files, not the dynamic store.
    # Its filenames are an existing registry contract, never guessed circuit keys.
    path=Path(public)/'austin-calibration.json'
    if path.exists():
        record={'asset':'public-austin-reference','kind':'public-reference','integrity':'invalid','identity':{'id':'austin','name':'Austin','year':year}}
        try:
            calibration=read_json(path)
            from .corner_import import geometry_id
            from .calibration_math import metrics
            import numpy as np
            p=np.array([[p['x'],p['y']] for p in calibration['geometry']['points']])
            if calibration.get('source')!='LiveF1' or calibration.get('circuitId')!='austin' or not calibration['validation'].get('automaticChecksPassed') or calibration.get('provenance',{}).get('synthetic') or len(p)<45 or not np.isfinite(p).all() or np.linalg.norm(p[0]-p[-1])>.01 or not np.isfinite(metrics(p,p)['rms']):raise ValueError('Invalid public calibration')
            fingerprint=geometry_id(p);annotations={}
            for kind in ('corners','sectors'):
                file=Path(public)/f'austin-{kind}.json'
                if file.exists():
                    value=read_json(file)
                    if value.get('geometryId')!=fingerprint or value.get('circuitId')!='austin' or value.get('layoutVersion')!=calibration['layoutVersion']:raise ValueError('Public annotation mismatch')
                    annotations[kind]=value
            provenance=calibration.get('provenance',{})
            paths=provenance.get('sessionPaths',[])
            source_years=sorted({int(str(p)[:4]) for p in paths if re.match(r'^20\d\d/',str(p))})
            record.update(integrity='valid',identity={'id':'austin','name':'Austin','year':year,'layoutVersion':calibration['layoutVersion'],'circuitKey':None},
                          sourceYears=source_years,complete=annotations_complete(annotations),geometryId=fingerprint,
                          calibration=calibration['validation'],cornerCount=len(annotations.get('corners',{}).get('corners',[])))
        except Exception as exc:record['error']=safe_exception(exc,'cache')
        records.append(record)
    return records


def session_candidates(event,catalog,year,now):
    candidates=[]
    for session in catalog:
        circuit=session.get('circuit') or {}
        if session.get('year')!=year or not circuit.get('Key') or not session.get('path'):continue
        # Venue aliases separate Barcelona/Madrid and Austin/Miami/Las Vegas.
        if not matches(event,session.get('location',''),circuit.get('ShortName','')):continue
        try:start=datetime.fromisoformat(session['start'].replace('Z','+00:00'))
        except (KeyError,TypeError,ValueError):continue
        if start.tzinfo is None:start=start.replace(tzinfo=timezone.utc)
        # A session less than 6h old is not assumed to be completed/published.
        if start.timestamp()+21600>now:continue
        if session.get('session') not in ('Race','Qualifying','Practice 3','Practice 2','Practice 1'):continue
        candidates.append(session)
    return sorted(candidates,key=lambda s:(s['session']!='Race',-datetime.fromisoformat(s['start'].replace('Z','+00:00')).timestamp()))


def summary(report):
    counts=Counter(row['status'] for row in report['queue'])
    return {'total':len(report['queue']),**{k:counts[k] for k in ('already-prepared','newly-prepared','partial','failed','unavailable','blocked','queued','preparing','skipped')}}


def run(year,root,public,dry_run=False,resume=True,lister=None,preparer=prepare,now=None,emit=print,fallback_years=2):
    now=time.time() if now is None else now
    cal=calendar(year);root=Path(root);directory=root/f'season-{year}'
    records=inventory(root,public,year) # before any source download
    previous={}
    if (directory/'report.json').exists():
        try:previous=read_json(directory/'report.json')
        except (OSError,ValueError):pass
    old={r['eventId']:r for r in previous.get('queue',[])} if resume else {}
    report={'schema':'season-preparation-report-v1','year':year,'calendar':cal,'startedAt':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'cacheLocations':{'gps':str(root/'gps-cache'),'fastf1':str(root/'fastf1-cache'),'sources':str(root/'annotation-sources')},
            'inventory':[{k:v for k,v in r.items() if k not in ('bundle',)} for r in records],'queue':[],'discoveryErrors':{}}
    def save():
        report['updatedAt']=datetime.now(timezone.utc).isoformat();report['summary']=summary(report)
        report['humanSummary']=', '.join(f'{k}: {v}' for k,v in report['summary'].items())
        if not dry_run:atomic(directory/'report.json',report)
    for event in cal['events']:
        found=[r for r in records if r.get('identity') and matches(event,r['identity']['name'],r['identity'].get('id',''))]
        row={'eventId':event['id'],'name':event['name'],'status':'queued','attempts':old.get(event['id'],{}).get('attempts',0)}
        if len(found)>1:row.update(status='blocked',reason='multiple-existing-assets; review without automatic repair')
        elif found:
            item=found[0];row['asset']=item['asset'];row['identity']=item['identity']
            if item['integrity']!='valid':row.update(status='blocked',reason='invalid-existing-asset')
            elif item.get('kind')=='public-reference':
                row.update(status='already-prepared' if item['complete'] and year in item['sourceYears'] else 'partial',reason='protected-public-reference; source-season/annotations require review' if not(item['complete'] and year in item['sourceYears']) else 'existing-public-registry',protected=True)
            else:
                from .preparation_audit import audit_bundle
                row['status']='already-prepared' if item['complete'] else 'queued';row['geometryReused']=True
                row['details']=audit_bundle(item['bundle'],Path(root)/item['asset'])
                row.update(sourceSeason=item['identity']['year'],targetSeason=year)
        # Corrupt pointers lack trustworthy identity: protect matching asset when
        # the real session circuit key becomes available below.
        row.setdefault('nextRetryAt',0)
        report['queue'].append(row)
    save()
    if dry_run:
        for i,row in enumerate(report['queue'],1):emit(f"[{i}/{len(report['queue'])}] {row['name']} — {row['status']}")
        return report
    from .archive import list_sessions
    lister=lister or list_sessions
    catalogs={}
    def catalog(source_year):
        if source_year in catalogs:return catalogs[source_year]
        path=directory/f'sessions-{source_year}.json'
        if path.exists():
            value=read_json(path)
            # Refresh short metadata catalogs after 24h; no telemetry here.
            if now-value.get('retrievedAt',0)<86400:
                catalogs[source_year]=value['sessions'];return catalogs[source_year]
        try:
            value=lister(source_year)
            atomic(path,{'year':source_year,'retrievedAt':now,'sessions':value});catalogs[source_year]=value
        except Exception as exc:
            report['discoveryErrors'][str(source_year)]=safe_exception(exc,'archive');catalogs[source_year]=[]
        return catalogs[source_year]
    store=AssetStore(root)
    for index,(event,row) in enumerate(zip(cal['events'],report['queue']),1):
        emit(f"[{index}/{len(report['queue'])}] {row['name']} — {row['status']}")
        if row['status']!='queued':continue
        earlier=old.get(event['id'],{})
        if earlier.get('nextRetryAt',0)>now:
            row.update(status='skipped',reason='retry-backoff',nextRetryAt=earlier['nextRetryAt'],lastStatus=earlier.get('lastStatus',earlier.get('status')))
            for key in ('selectedSession','selectionReason','failureCategory','error','sourceError','fallbackCandidates','sourceSeason','targetSeason'):
                if key in earlier:row[key]=earlier[key]
            save();continue
        candidates=session_candidates(event,catalog(year),year,now)
        if not candidates:
            discovery_error=report['discoveryErrors'].get(str(year),{})
            if discovery_error.get('code')=='authentication-required':
                row.update(status='failed',failureCategory='authentication',error=discovery_error,nextRetryAt=now+300);save();emit(f"[{index}/{len(report['queue'])}] {row['name']} — failed: authentication");continue
            alternatives=[]
            for earlier_year in range(year-1,max(2018,year-fallback_years)-1,-1):
                alternatives.extend(session_candidates(event,catalog(earlier_year),earlier_year,now))
            # Stable circuit keys alone never prove cross-season geometry identity.
            row.update(status='unavailable',reason='no-completed-target-season-session' if not alternatives else 'older-source-found-layout-compatibility-unverified',
                       fallbackCandidates=[{'year':s['year'],'path':s['path'],'circuit':s['circuit'],'session':s['session']} for s in alternatives[:5]],nextRetryAt=now+3600)
            save();emit(f"[{index}/{len(report['queue'])}] {row['name']} — unavailable: {row['reason']}");continue
        if row.get('geometryReused'):
            preferred=[s for s in candidates if s['path']==row['identity']['path']]
            if not preferred:
                row.update(status='partial',reason='existing-geometry-source-not-currently-available; no session substitution');save();continue
            candidates=preferred
        row['candidates']=[{'path':s['path'],'session':s['session'],'year':s['year']} for s in candidates]
        for selected in candidates:
            meta=identity(selected)
            if any(r['asset']==meta['assetKey'] and r['integrity']=='invalid' for r in records):
                row.update(status='blocked',reason='corrupt-existing-asset; no destructive repair');break
            row.update(status='preparing',sourceSeason=selected['year'],targetSeason=year,selectedSession=selected,
                       selectionReason='completed published target-season Race preferred; real metadata identity',attempts=row['attempts']+1)
            save()
            def progress(**value):
                emit(f"[{index}/{len(report['queue'])}] {row['name']} — {value.get('stage','preparing')}")
            try:
                result=preparer(selected,store=store,report=progress)
                from .preparation_audit import audit_bundle
                row.update(status='newly-prepared' if annotations_complete(result) else 'partial',asset=meta['assetKey'],
                           details=audit_bundle(result,store.directory(meta['assetKey'])),nextRetryAt=0 if annotations_complete(result) else now+300)
                break # valid geometry never replaced by another session
            except Exception as exc:
                row.update(status='failed',error=safe_exception(exc,'build'),nextRetryAt=now+300)
                # Existing geometry, corrupt assets or auth failures are not
                # repaired/replaced by trying a different session.
                diagnostic=store.directory(meta['assetKey'])/'geometry-diagnostics.json'
                if diagnostic.exists():
                    try:
                        attempts=read_json(diagnostic).get('windows',[])
                        source_error=next((w['error'] for w in reversed(attempts) if w.get('error')),None)
                        if source_error:row['sourceError']=source_error
                        if source_error and source_error.get('code')=='authentication-required':
                            row['failureCategory']='authentication';break
                    except (ValueError,OSError):pass
                if store.get(meta) is not None or report['discoveryErrors']:break
            finally:save()
        save();emit(f"[{index}/{len(report['queue'])}] {row['name']} — {row['status']}")
    save();emit(report['humanSummary']);return report


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--year',type=int,required=True);parser.add_argument('--store',default='circuit-assets')
    parser.add_argument('--public',default='public/circuits');parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Resume is automatic; accepted for clarity')
    parser.add_argument('--login',action='store_true');args=parser.parse_args()
    if args.dry_run:
        report=run(args.year,args.store,args.public,dry_run=True)
        print(json.dumps(report,indent=2));return
    root=Path(args.store);directory=root/f'season-{args.year}';directory.mkdir(parents=True,exist_ok=True)
    lock=directory/'season.lock'
    import os
    if lock.exists():
        try:pid=read_json(lock)['pid']
        except Exception:parser.error('Unrecognized season lock; inspect before retrying')
        if process_alive(pid):parser.error('Season batch is already running')
        lock.unlink()
    try:
        with lock.open('x') as handle:json.dump({'pid':os.getpid()},handle)
    except FileExistsError:parser.error('Another season batch acquired the lock')
    try:
        if args.login:
            from livef1 import login
            login()
        result=run(args.year,args.store,args.public)
        if any(r['status'] not in ('already-prepared','newly-prepared') for r in result['queue']):raise SystemExit(2)
    finally:lock.unlink(missing_ok=True)


if __name__=='__main__':main()
