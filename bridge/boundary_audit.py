"""Shareable local audit: geometry/annotation numbers only, no account or raw feed."""
import argparse
import json
from pathlib import Path

import numpy as np

from .corner_import import ImportFailure, read, write, geometry_id, project_corner
from .sector_import import KEYS, fia_check


def arc_point(points, fraction):
    p=np.asarray(points,dtype=float)
    lengths=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
    distance=float(np.clip(fraction,0,1))*lengths[-1]
    i=min(len(p)-1,max(1,int(np.searchsorted(lengths,distance,side='left'))))
    span=lengths[i]-lengths[i-1]
    return p[i-1]+(p[i]-p[i-1])*((distance-lengths[i-1])/span if span else 0)


def audit(calibration,corners,sectors,manual=None,source=None,browser=None,physical=None):
    for item in (corners,sectors):
        if item.get('circuitId')!=calibration['circuitId'] or item.get('layoutVersion')!=calibration['layoutVersion']:
            raise ImportFailure('Audit circuit/layout mismatch')
    native=np.array([[p['x'],p['y']] for p in calibration['geometry']['points']],dtype=float)
    fingerprint=geometry_id(native)
    if any(item.get('geometryId')!=fingerprint for item in (corners,sectors)):
        raise ImportFailure('Audit geometry mismatch')
    projected=np.column_stack([native[:,0]-native[:,0].min()+650,native[:,1].max()-native[:,1]+650])
    length=float(np.linalg.norm(np.diff(native,axis=0),axis=1).sum())
    direction=sectors['direction']
    result={'schema':'f1-boundary-audit-v1','circuitId':calibration['circuitId'],'layoutVersion':calibration['layoutVersion'],
            'geometryId':fingerprint,'pathLengthNative':length,'direction':direction,'boundaries':[], 'cornerAnchors':[],
            'precision':{k:sectors[k].get('sourceEstimate',{}).get('statistics') for k in KEYS},
            'accuracy':{'status':'unverified','reason':'No independently registered physical timing-line coordinates supplied'},
            'warnings':[], 'contains':'Only geometry/annotation summaries, aggregate timing offsets; no tokens, account details, raw UTC or recordings'}
    for k in KEYS:
        at=sectors[k]['at']
        result['boundaries'].append({'key':k,'storedSectorAt':at,'nativePoint':arc_point(native,at).tolist(),
            'expectedSvgPoint':arc_point(projected,at).tolist(),'manualFileAt':manual.get(k,{}).get('at') if manual and manual.get(k) else None})
    for c in corners.get('corners',[]):
        p=arc_point(projected,c['at'])
        result['cornerAnchors'].append({'number':c['number'],'letter':c.get('letter',''),'at':c['at'],'svgAnchor':p.tolist(),
            'labelOffset':c.get('offset'),'status':c.get('status')})
    # FIA diagnostics explicitly use SAVED corner anchors, not a newly imported set.
    checked={**sectors,'corners':corners.get('corners',[])}
    result['fiaUsingSavedCorners']=fia_check(checked)
    result['originalFiaDiagnostics']=sectors.get('boundaryDiagnostics',{}).get('fia')
    if source:
        reg=sectors.get('boundaryDiagnostics',{}).get('registration',sectors.get('alignment',{}))
        if reg.get('matrix') is not None:
            matrix=np.array(reg['matrix']);translation=np.array(reg['translation'])
            saved={(c['number'],c.get('letter','')):c for c in corners.get('corners',[])}
            differences=[]
            for c in source.get('corners',[]):
                p=np.array([c['x'],c['y']])@matrix+translation
                try:at,error=project_corner(p,native,reg['extent'])
                except ImportFailure as exc:
                    differences.append({'number':c['number'],'letter':c.get('letter',''),'projectionFailure':str(exc)});continue
                old=saved.get((c['number'],c.get('letter','')))
                differences.append({'number':c['number'],'letter':c.get('letter',''),'reprojectedSourceAt':at,
                    'savedCornerAt':old['at'] if old else None,'differenceNative':((at-old['at']+.5)%1-.5)*length if old else None,'projectionError':error})
            result['sourceVsSavedCorners']=differences
        offsets=[lap.get('sectorSessionOffsets',lap.get('timingReceiptOffsets')) for lap in source.get('boundaryLaps',{}).get('laps',[])]
        result['sectorSessionOffsetSeconds']={}
        for i,k in enumerate(('sector1End','sector2End','lapEnd')):
            values=[v[i] for v in offsets if v and len(v)>i and v[i] is not None and np.isfinite(v[i])]
            result['sectorSessionOffsetSeconds'][k]={'count':len(values),'median':float(np.median(values)) if values else None,
                'note':'Parsed FastF1 sector SessionTimes may already be latency-corrected. Differences do not establish a GPS correction.'}
        result['cachedSelection']={'retainedLaps':len(source.get('boundaryLaps',{}).get('laps',[])),
            'previouslyRejected':source.get('boundaryLaps',{}).get('rejected',{}),
            'note':'Rejected laps were not retained in old normalized JSON; reuse the FastF1 raw cache offline to collect them under the boundary-local gap policy.'}
    if physical:
        from .physical_lines import intersect_lines
        hits,total=intersect_lines(physical,sectors,native)
        result['accuracy']={'status':'independent-reference-supplied-unverified','differencesNative':{k:((sectors[k]['at']-hits[k]['at']+.5)%1-.5)*total for k in KEYS},'referenceProvenance':physical['provenance']}
    if browser:
        if browser.get('geometryId')!=fingerprint:raise ImportFailure('Browser audit geometry mismatch')
        result['browserBoundaries']=browser.get('boundaries',[])
        for row in browser.get('boundaries',[]):
            calculated=next((b['storedSectorAt'] for b in result['boundaries'] if b['key']==row['key']),None)
            if calculated is not None and row.get('displayedAt') is not None and abs((row['displayedAt']-calculated+.5)%1-.5)>1e-6:
                result['warnings'].append(f"{row['key']}: browser displays an override ({row['displayedAt']:.6f}), sector file stores {calculated:.6f}")
        rendered=[]
        for segment in browser.get('renderedSegments',[]):
            errors=[]
            for edge in ('start','end'):
                expected=arc_point(projected,segment[edge+'At'])
                observed=segment[edge]
                errors.append(float(np.linalg.norm(expected-[observed['x'],observed['y']])))
            rendered.append({'sector':segment['sector'],'startErrorNative':errors[0],'endErrorNative':errors[1]})
        result['renderedEndpointErrors']=rendered
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('calibration','corners','sectors','output'):p.add_argument('--'+key,required=True)
    for key in ('annotations','source','browser-audit','physical-reference'):p.add_argument('--'+key)
    args=p.parse_args()
    try:
        optional=lambda path:read(path) if path and Path(path).exists() else None
        result=audit(read(args.calibration),read(args.corners),read(args.sectors),optional(args.annotations),optional(args.source),optional(args.browser_audit),optional(args.physical_reference))
        write(args.output,result)
        print(json.dumps({'warnings':result['warnings'],'fia':result['fiaUsingSavedCorners'],'accuracy':result['accuracy']},indent=2))
    except ImportFailure as exc:p.exit(1,f'Boundary audit failed: {exc}\n')
    except Exception as exc:p.exit(1,f'Boundary audit failed ({type(exc).__name__}). Check input files; no credentials are needed.\n')


if __name__=='__main__':main()
