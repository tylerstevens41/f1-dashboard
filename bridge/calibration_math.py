"""Source-coordinate trajectory reconstruction and measured SVG registration."""
import math
import re
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree


def resample(points, count=512, closed=True):
    points = np.asarray(points, dtype=float)
    if len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('Invalid trajectory')
    if closed and np.linalg.norm(points[0]-points[-1]) > 1e-8:
        points = np.vstack([points, points[0]])
    distances = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    unique = np.r_[True, np.diff(distances) > 1e-8]
    points, distances = points[unique], distances[unique]
    if distances[-1] <= 0:
        raise ValueError('Degenerate trajectory')
    positions = np.linspace(0,distances[-1],count,endpoint=not closed)
    return np.column_stack([np.interp(positions,distances,points[:,i]) for i in (0,1)])


def segment_errors(points, path):
    points = np.asarray(points, dtype=float)
    path = np.asarray(path, dtype=float)
    a, b = path, np.roll(path,-1,axis=0)
    v = b-a
    denominator = np.maximum((v*v).sum(axis=1),1e-12)
    output=[]
    for batch in np.array_split(points,max(1,math.ceil(len(points)/512))):
        delta = batch[:,None,:]-a[None,:,:]
        t = np.clip((delta*v[None,:,:]).sum(axis=2)/denominator,0,1)
        residual = delta-t[:,:,None]*v[None,:,:]
        output.extend(np.sqrt((residual*residual).sum(axis=2).min(axis=1)))
    return np.asarray(output)


def metrics(points, path):
    error = segment_errors(points,path)
    diagonal = float(np.linalg.norm(np.ptp(np.asarray(path),axis=0)))
    return {'median':float(np.median(error)), 'p95':float(np.percentile(error,95)),
            'rms':float(np.sqrt(np.mean(error**2))), 'max':float(error.max()),
            'p95FractionOfDiagonal':float(np.percentile(error,95)/diagonal),
            'units':'LiveF1 coordinate units (not assumed metres)'}


def similarity(source, target):
    x,y=np.asarray(source),np.asarray(target)
    xc,yc=x-x.mean(0),y-y.mean(0)
    u,s,vt=np.linalg.svd(xc.T@yc)
    sign=np.ones(2)
    if np.linalg.det(u@vt)<0: sign[-1]=-1
    rotation=u@np.diag(sign)@vt
    scale=float((s*sign).sum()/max((xc*xc).sum(),1e-12))
    matrix=(scale*rotation).T
    translation=y.mean(0)-x.mean(0)@matrix.T
    return matrix,translation


def register_svg(svg_points, trajectory):
    """Multi-start similarity/reflection ICP, then constrained diagnostic affine ICP.

    This is a geometric comparison, not proof of corner correspondence or start
    line accuracy. Coverage is checked symmetrically to avoid subset-only fits.
    """
    source=resample(svg_points,256)
    target=resample(trajectory,512)
    tree=cKDTree(target)
    center=source.mean(0)
    radius=np.sqrt(np.mean(((source-center)**2).sum(1)))
    target_radius=np.sqrt(np.mean(((target-target.mean(0))**2).sum(1)))
    best=None
    for reflected in (False,True):
        mirror=np.diag([1,-1 if reflected else 1])
        base=(source-center)@mirror
        for angle in np.linspace(0,2*np.pi,24,endpoint=False):
            rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
            matrix=rotation*target_radius/radius
            offset=target.mean(0)
            for _ in range(35):
                transformed=base@matrix.T+offset
                distance,index=tree.query(transformed)
                keep=distance<=np.percentile(distance,90)
                updated,translation=similarity(base[keep],target[index[keep]])
                if np.linalg.norm(matrix-updated)+np.linalg.norm(offset-translation)<1e-7:
                    break
                matrix,offset=updated,translation
            transformed=base@matrix.T+offset
            score=float(np.mean(tree.query(transformed)[0]**2)+np.mean(cKDTree(transformed).query(target)[0]**2))
            if best is None or score<best[0]:
                canonical=matrix@mirror
                best=(score,canonical,offset-center@canonical.T,reflected)
    _,matrix,offset,_=best
    sim=source@matrix.T+offset
    affine_matrix,affine_offset=matrix.copy(),offset.copy()
    for _ in range(25):
        distances,index=tree.query(source@affine_matrix.T+affine_offset)
        keep=distances<=np.percentile(distances,90)
        fitted=np.linalg.lstsq(np.c_[source[keep],np.ones(sum(keep))],target[index[keep]],rcond=None)[0]
        if np.linalg.cond(fitted[:2].T)>10:
            break
        affine_matrix,affine_offset=fitted[:2].T,fitted[2]
    affine=source@affine_matrix.T+affine_offset
    def result(m,t,points):
        singular=np.linalg.svd(m,compute_uv=False)
        return {'matrix':[float(m[0,0]),float(m[1,0]),float(m[0,1]),float(m[1,1]),float(t[0]),float(t[1])],
                'trajectoryToOutline':metrics(target,points),'outlineToTrajectory':metrics(points,target),
                'scaleRatio':float(singular.max()/singular.min()),'reflected':bool(np.linalg.det(m)<0),
                'rotationDegrees':float(np.degrees(np.arctan2(m[1,0],m[0,0]))),
                'points':points.tolist()}
    return {'similarity':result(matrix,offset,sim),'affine':result(affine_matrix,affine_offset,affine),
            'warning':'ICP correspondence requires visual review; start/finish is not established by an unordered shape fit.'}


def svg_transform(text):
    result=np.eye(3)
    for name,args in re.findall(r'(matrix|translate|scale|rotate)\s*\(([^)]*)\)',text or ''):
        v=[float(x) for x in re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?',args)]
        m=np.eye(3)
        if name=='matrix' and len(v)==6:
            m=np.array([[v[0],v[2],v[4]],[v[1],v[3],v[5]],[0,0,1]])
        elif name=='translate':m[:2,2]=[v[0],v[1] if len(v)>1 else 0]
        elif name=='scale':m[0,0],m[1,1]=v[0],v[1] if len(v)>1 else v[0]
        elif name=='rotate':
            angle=np.radians(v[0]);m[:2,:2]=[[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]]
            if len(v)==3:
                center=np.array(v[1:]);m[:2,2]=center-m[:2,:2]@center
        else:raise ValueError('Unsupported SVG transform')
        result=result@m
    # Refuse unsupported transforms instead of silently mis-registering geometry.
    if re.sub(r'(matrix|translate|scale|rotate)\s*\([^)]*\)','',text or '').strip(' ,\t\n'):
        raise ValueError('Unsupported SVG transform; convert to matrix first')
    return result


def sample_svg(filename, path_id=None, count=512):
    from svgpathtools import parse_path
    root=ET.parse(filename).getroot()
    candidates=[]
    def visit(node,parent):
        matrix=parent@svg_transform(node.get('transform',''))
        if node.tag.split('}')[-1]=='path' and node.get('d') and (path_id is None or node.get('id')==path_id):
            path=parse_path(node.get('d'))
            if not path.iscontinuous() or not path.isclosed():
                raise ValueError('Calibration needs a continuous closed centreline path')
            points=[]
            length=path.length()
            for fraction in np.linspace(0,1,count,endpoint=False):
                point=path.point(path.ilength(float(fraction*length)))
                points.append((matrix@np.array([point.real,point.imag,1]))[:2])
            candidates.append((length,node.get('id'),np.array(points)))
        for child in node:visit(child,matrix)
    visit(root,np.eye(3))
    if not candidates:raise ValueError('No matching closed SVG path')
    chosen=max(candidates,key=lambda p:p[0])
    return chosen[2],chosen[1]
