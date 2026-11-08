"""Ordered-loop checks: a 2-D crossover never creates a new connection."""
import numpy as np


def direction_consensus(laps):
    """Compare measured lap order, allowing cyclic origin changes, not reversal.

    Used only when signed area is unusable (e.g. cancelling figure-eight lobes).
    Every phase comparison preserves all original point adjacency. No sorting
    by XY, nearest-neighbor routing, crossover snapping or geometry edits.
    """
    reference=np.asarray(laps[0]['points'],dtype=float)
    extent=float(np.linalg.norm(np.ptp(reference,axis=0)))
    if extent<=0:return {'passed':False,'reason':'degenerate-extent'}
    scores=[]
    for lap in laps[1:]:
        points=np.asarray(lap['points'],dtype=float)
        if points.shape!=reference.shape:return {'passed':False,'reason':'inconsistent-sampling'}
        def best(values):
            return min(float(np.median(np.linalg.norm(np.roll(values,shift,axis=0)-reference,axis=1))) for shift in range(len(values)))
        forward,reverse=best(points),best(points[::-1])
        scores.append({'forwardFractionOfExtent':forward/extent,'reverseFractionOfExtent':reverse/extent})
        if reverse<=max(forward*1.25,extent*.001):
            return {'passed':False,'reason':'reversed-or-ambiguous-ordered-lap','comparisons':scores}
    return {'passed':True,'method':'ordered-cyclic-trajectory','comparisons':scores}


def crossover_audit(points):
    """Report projected intersections between nonadjacent ordered segments.

    This cannot determine bridge height or prove a real circuit's connectivity.
    Indices/fractions identify separate visits to a shared XY location.
    """
    p=np.asarray(points,dtype=float)
    if len(p)<4 or len(p)>4096 or not np.isfinite(p).all():raise ValueError('Invalid bounded geometry')
    if np.linalg.norm(p[0]-p[-1])>1e-8:p=np.vstack([p,p[0]])
    vectors=np.diff(p,axis=0);sizes=np.linalg.norm(vectors,axis=1)
    lengths=np.r_[0,np.cumsum(sizes)]
    if lengths[-1]<=0:raise ValueError('Degenerate geometry')
    found=[]
    for i,v in enumerate(vectors):
        js=np.arange(i+2,len(vectors))
        if i==0:js=js[js!=len(vectors)-1]
        if not len(js):continue
        w=vectors[js];delta=p[js]-p[i]
        cross=v[0]*w[:,1]-v[1]*w[:,0]
        valid=np.abs(cross)>1e-9
        t=np.divide(delta[:,0]*w[:,1]-delta[:,1]*w[:,0],cross,out=np.zeros(len(js)),where=valid)
        u=np.divide(delta[:,0]*v[1]-delta[:,1]*v[0],cross,out=np.zeros(len(js)),where=valid)
        for index in np.where(valid&(t>=-1e-9)&(t<=1+1e-9)&(u>=-1e-9)&(u<=1+1e-9))[0]:
            j=int(js[index]);a=float((lengths[i]+t[index]*sizes[i])/lengths[-1])%1;b=float((lengths[j]+u[index]*sizes[j])/lengths[-1])%1
            pair=sorted([a,b])
            if min(abs(a-b),1-abs(a-b))<.01:continue
            if any(max(min(abs(x-y),1-abs(x-y)) for x,y in zip(pair,old['fractions']))<.005 for old in found):continue
            found.append({'segments':[i,j],'fractions':pair})
    return {'method':'ordered-nonadjacent-segment-intersections','projectedCrossings':found,
            'connectivity':'original-sample-adjacency-retained','heightVerified':False,
            'warning':'2-D crossings are not junctions. Independent visual/source validation is still required.'}
