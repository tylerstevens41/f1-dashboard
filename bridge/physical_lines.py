"""Optional independent timing-line intersections; no guessed Austin coordinates."""
import math
import numpy as np
from .corner_import import ImportFailure

KEYS=('startFinish','sector1End','sector2End')


def intersect_lines(reference,result,points):
    if reference.get('schema')!='circuit-physical-timing-lines-v1' or any(reference.get(k)!=result.get(k) for k in ('circuitId','layoutVersion','geometryId')):
        raise ImportFailure('Physical timing-line circuit/layout/geometry mismatch')
    if reference.get('season')!=result.get('sectorSource',{}).get('year') or not reference.get('provenance'):
        raise ImportFailure('Physical timing lines require matching season and independently sourced provenance')
    p=np.asarray(points,dtype=float);lengths=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
    cross=lambda a,b:float(a[0]*b[1]-a[1]*b[0])
    result_at={}
    for key in KEYS:
        line=reference.get('lines',{}).get(key,{})
        a=np.asarray(line.get('a'),dtype=float);b=np.asarray(line.get('b'),dtype=float)
        uncertainty=line.get('uncertaintyNative')
        if a.shape!=(2,) or b.shape!=(2,) or not np.isfinite([a,b]).all() or np.linalg.norm(b-a)<=0 or not isinstance(uncertainty,(int,float)) or not math.isfinite(uncertainty) or uncertainty<=0:
            raise ImportFailure('Physical line requires two finite native endpoints and positive registration uncertainty')
        hits=[]
        for i in range(1,len(p)):
            r=p[i]-p[i-1];s=b-a;den=cross(r,s)
            if abs(den)<1e-10:continue
            t=cross(a-p[i-1],s)/den;u=cross(a-p[i-1],r)/den
            if 0<=t<=1 and 0<=u<=1:
                at=float((lengths[i-1]+t*np.linalg.norm(r))/lengths[-1])%1
                if not any(abs((at-h+.5)%1-.5)<1e-7 for h in hits):hits.append(at)
        if len(hits)!=1:raise ImportFailure(f'{key}: physical timing line must intersect exactly one track section')
        result_at[key]={'at':hits[0],'uncertaintyNative':uncertainty}
    s,a,b=[result_at[k]['at'] for k in KEYS];direction=result['direction']
    if not 0<((a-s)*direction)%1<((b-s)*direction)%1<1:raise ImportFailure('Physical timing-line order disagrees with driving direction')
    return result_at,float(lengths[-1])


def apply_physical_lines(reference,result,calibration):
    points=[[p['x'],p['y']] for p in calibration['geometry']['points']]
    hits,length=intersect_lines(reference,result,points)
    differences={}
    for key,hit in hits.items():
        old=result.get(key)
        differences[key]=((old['at']-hit['at']+.5)%1-.5)*length if old else None
        stats={'p95LapFraction':hit['uncertaintyNative']/length,'p95NativeDistance':hit['uncertaintyNative'],
               'note':'Supplied map-registration uncertainty, not lap-to-lap GPS spread'}
        result[key]={'at':hit['at'],'status':'provisional','calculated':True,'method':'independent-physical-line-intersection',
                     'sourceEstimate':{'at':hit['at'],'statistics':stats},'timingEstimate':old}
    result['physicalReference']={'provenance':reference['provenance'],'season':reference['season'],'version':reference.get('version')}
    result.setdefault('boundaryDiagnostics',{})['accuracy']={'status':'independent-reference-supplied-unverified',
        'timingMinusPhysicalNative':differences,'note':'Uses explicitly supplied registered physical line endpoints; never fits a time offset or assumes reference registration is verified.'}
    return result
