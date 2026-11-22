"""Target one event using eligible current-season archives, never older layouts.

Offline geometry/calibration still uses the existing preparation coordinator.
Authentication, downloaded telemetry and assets stay on the local computer.
"""
import argparse
import json
from pathlib import Path
import time
import uuid

from .autonomous import utc_start
from .diagnostics import safe_exception
from .preparation import (AssetStore, PreparationError, DEFAULT_STORE, atomic_json,
                          identity, prepare, collect_geometry, import_annotations, slug)
from .season_preparation import normalized
from .window_scan import find_usable_window


def candidates(catalog, year, event, now):
    """Six-hour archive eligibility is conservative, not proof of completion.

    Accepted full measured laps and calibration checks remain authoritative.
    Identity comes only from provider metadata. Unknown timezone is excluded.
    """
    if not isinstance(catalog,list):raise PreparationError('Unexpected provider session catalog schema')
    found={}
    for session in catalog:
        if not isinstance(session,dict) or session.get('year')!=year:continue
        names=' '.join(str(session.get(k,'')) for k in ('event','location'))+' '+str((session.get('circuit') or {}).get('ShortName',''))
        if f' {normalized(event)} ' not in f' {normalized(names)} ':continue
        if session.get('session') not in ('Race','Qualifying','Practice 3','Practice 2','Practice 1'):continue
        start=utc_start(session)
        if start is None or start+21600>now:continue
        path=session.get('path')
        if not isinstance(path,str) or not path.startswith(f'{year}/'):continue
        identity(session)  # Stable key/name/layout required, never guessed.
        if path in found and identity(found[path])['circuitKey']!=identity(session)['circuitKey']:
            raise PreparationError('Conflicting provider circuit identities for one session path')
        found[path]=session
    result=sorted(found.values(),key=lambda s:(s['session']!='Race',-utc_start(s),s['path']))
    if len({identity(s)['circuitKey'] for s in result})>1:
        raise PreparationError('Event matches multiple circuit identities; use a more specific venue name')
    return result


def run(year,event,store,geometry_only=False,annotations_only=False,session='auto',
        lister=None,scanner=find_usable_window,collector=collect_geometry,
        importer=import_annotations,now=None,emit=lambda **_:None):
    from .archive import list_sessions
    from .preparation_audit import audit_bundle
    now=time.time() if now is None else now
    if geometry_only and annotations_only:raise PreparationError('Choose only one preparation stage')
    diagnostic={'schema':'event-preparation-run-v1','targetYear':year,'event':event,
                'startedAt':now,'status':'discovering','attempts':[],
                'policy':'current-season only; no historical layout compatibility waiver'}
    report_path=store.root/'event-runs'/f'{slug(event)}-{year}-{uuid.uuid4().hex}.json'
    def save():atomic_json(report_path,diagnostic)
    save()
    def measured_collector(meta,cache,report,windows):
        stats={}
        report(stage='window-discovery',state='preparing',scan=stats)
        try:
            offset=scanner(meta['path'],0,stats,on_progress=lambda:report(stage='window-discovery',state='preparing',scan=stats))
        except Exception as exc:
            stats['error']=safe_exception(exc,'archive');raise
        finally:
            diagnostic['attempts'][-1]['windowDiscovery']=stats
            save()
            report(stage='window-discovery',state='preparing',scan=stats)
        # Same complete-lap, held-out, spatial coverage and direction checks.
        return collector(meta,cache,report,windows=(offset,))
    try:
        eligible=candidates((lister or list_sessions)(year),year,event,now)
        if session!='auto':eligible=[s for s in eligible if s['session']==session]
        diagnostic['candidates']=eligible
        if not eligible:
            diagnostic.update(status='unavailable',reason='no-eligible-current-season-archive; retry after publication, or inspect metadata/timezones')
            return diagnostic
        existing=store.lookup(year,circuit_key=identity(eligible[0])['circuitKey'])
        if existing:
            # Resume original source/checkpoints; never silently switch annotations.
            matching=[s for s in eligible if s['path']==existing['identity']['path']]
            if not matching:raise PreparationError('Existing geometry source is not among eligible sessions; preserve assets and select its source explicitly')
            eligible=matching
        if annotations_only and not existing:raise PreparationError('Annotations-only requires existing accepted geometry')
        for source in eligible:
            meta=identity(source)
            attempt={'identity':meta,'reason':'existing geometry source' if existing else 'eligible same-season provider session; newest non-race when race unavailable'}
            diagnostic['attempts'].append(attempt)
            diagnostic.update(status='preparing',selectedSession=source)
            save();emit(stage='source-selected',identity=meta,reason=attempt['reason'])
            try:
                bundle=prepare(source,store,report=emit,collector=measured_collector,importer=importer,
                               geometry_only=geometry_only,annotations_only=annotations_only)
                attempt['status']='complete' if bundle['complete'] else 'geometry-ready'
                diagnostic.update(status=attempt['status'],audit=audit_bundle(bundle,store.directory(meta['assetKey'])),
                                  layoutCompatibility='same-season measured geometry; runtime LIVE GPS validation still required')
                return diagnostic
            except Exception as exc:
                attempt.update(status='failed',error=safe_exception(exc.__cause__ or exc.__context__ or exc,'archive'))
                # Coordinator already published any accepted geometry. Do not
                # regenerate it from another session after annotation failure.
                retained=store.get(meta)
                if retained:
                    diagnostic.update(status='geometry-ready',reason='annotation stage failed; geometry retained',
                                      audit=audit_bundle(retained,store.directory(meta['assetKey'])))
                    return diagnostic
                save()
                if attempt['error'].get('code')=='authentication-required':break
        diagnostic['status']='failed'
        return diagnostic
    except Exception as exc:
        diagnostic.update(status='failed',error=safe_exception(exc,'archive'))
        if isinstance(exc,PreparationError):diagnostic['reason']=str(exc)
        return diagnostic
    finally:
        diagnostic['finishedAt']=time.time();save()
        emit(stage='event-report',status=diagnostic['status'],report=str(report_path))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year',required=True,type=int);parser.add_argument('--event',required=True)
    parser.add_argument('--session',default='auto',choices=['auto','Race','Qualifying','Practice 3','Practice 2','Practice 1'])
    parser.add_argument('--store',default=str(DEFAULT_STORE));parser.add_argument('--login',action='store_true')
    group=parser.add_mutually_exclusive_group();group.add_argument('--geometry-only',action='store_true');group.add_argument('--annotations-only',action='store_true')
    args=parser.parse_args()
    if not 2018<=args.year<=2100:parser.error('Year must be 2018–2100')
    try:
        if args.login:
            from livef1 import login
            login()
        from .preparation import cli_progress
        result=run(args.year,args.event,AssetStore(args.store),args.geometry_only,args.annotations_only,args.session,emit=cli_progress)
        print(json.dumps(result,indent=2))
        return 0 if result['status'] in ('complete','geometry-ready') else 1
    except Exception as exc:
        print(json.dumps({'status':'failed','error':safe_exception(exc,'archive')}))
        return 1


if __name__=='__main__':raise SystemExit(main())
