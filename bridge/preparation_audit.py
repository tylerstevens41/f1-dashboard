"""Offline prepared-circuit report. Never fetches data or changes circuit assets."""
import argparse
from pathlib import Path
from .preparation import AssetStore,read_json,annotations_complete,validate_bundle
from .annotation_progress import atomic
from .trajectory_order import crossover_audit


def audit_bundle(bundle,directory):
    validate_bundle(bundle)
    calibration=bundle['calibration'];validation=calibration['validation']
    windows=validation.get('preparationDiagnostics',{}).get('windows',[])
    accepted=[w for w in windows if w.get('status')=='accepted']
    window=accepted[-1] if accepted else {}
    offset=calibration.get('provenance',{}).get('preparationWindowSeconds')
    sectors=bundle.get('sectors') or {};corners=bundle.get('corners') or {}
    return {'schema':'circuit-preparation-audit-v1','identity':bundle['identity'],
        'state':'annotation-complete' if annotations_complete(bundle) else 'geometry-ready',
        'verification':bundle.get('verification','provisional'),'liveCompatibility':bundle.get('liveCompatibility','not-checked'),
        'geometryId':bundle['geometryId'],'assets':str(directory),'gps':{k:window.get(k) for k in ('decodedPositionRecords','driversRepresented','candidateLaps','acceptedCompleteLaps','rejected','incompleteLapReasons','orderedDirection')},
        'calibration':{k:validation.get(k) for k in ('automaticChecksPassed','heldOut','lapCount','driverCount','rejected','verified')},
        'crossover':crossover_audit([[p['x'],p['y']] for p in calibration['geometry']['points']]),
        'annotations':{'corners':len(corners.get('corners',[])),'registration':corners.get('alignment'),
            'boundaries':{k:sectors.get(k) for k in ('startFinish','sector1End','sector2End')},'diagnostics':sectors.get('boundaryDiagnostics')},
        'testPlayback':{'sessionPath':bundle['identity']['path'],'offsetSeconds':offset,'durationSeconds':480,'speed':1,
            'verified':False,'reason':'Accepted geometry window is a TEST candidate, not proof of full-topic playback or visual GPS alignment.'},
        'warnings':bundle.get('warnings',[])}


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--year',type=int,required=True);parser.add_argument('--event',required=True)
    parser.add_argument('--store',default='circuit-assets');parser.add_argument('--report',required=True)
    args=parser.parse_args()
    output=Path(args.report)
    if output.exists():parser.error('Report already exists; select a new filename to preserve previous evidence')
    store=AssetStore(args.store);matches=[]
    for pointer in sorted(store.root.glob('*/current.json')):
        try:
            value=read_json(pointer);revision=value['revision']
            # Only the store's canonical revision names, never user-supplied paths.
            import re
            if not re.fullmatch(r'[0-9a-f]{32}',revision):continue
            bundle=read_json(pointer.parent/f'{revision}.json');meta=bundle['identity']
            if meta['year']==args.year and args.event.casefold() in (meta['name']+' '+meta['event']).casefold():matches.append(audit_bundle(bundle,pointer.parent))
        except (OSError,ValueError,KeyError):continue
    report={'schema':'circuit-preparation-audit-report-v1','year':args.year,'event':args.event,'circuits':matches,'state':'available' if matches else 'not-prepared'}
    atomic(output,report)
    print(f"{len(matches)} prepared circuit(s); audit written to {output}")
    return 0 if matches else 1


if __name__=='__main__':raise SystemExit(main())
