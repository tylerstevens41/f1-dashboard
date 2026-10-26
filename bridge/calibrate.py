"""Bounded local LiveF1 circuit calibration. Credentials never leave the backend."""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from .archive import fetch_clip, list_sessions, load_recording
from .protocol import RaceState, utc_ms
from .calibration_math import metrics, register_svg, resample, sample_svg

MAX_SAMPLES=180000


def read_json(path):
    path=Path(path)
    if path.stat().st_size>64*1024*1024:raise ValueError('Input exceeds 64 MiB')
    with path.open('rb') as f: compressed=f.read(2)==b'\x1f\x8b'
    with (gzip.open if compressed else open)(path,'rt',encoding='utf8') as f:
        text=f.read(64*1024*1024+1)
    if len(text)>64*1024*1024:raise ValueError('Input exceeds 64 MiB')
    return json.loads(text)


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(data,allow_nan=False,separators=(',',':'))
    if len(text)>64*1024*1024:raise ValueError('Output exceeds 64 MiB')
    temp=path.with_suffix('.tmp')
    try:
        with (gzip.open if path.suffix=='.gz' else open)(temp,'wt',encoding='utf8') as f:f.write(text)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def collect_clip(clip):
    from livef1.data_processing.etl import function_map
    state=RaceState('TEST');state.topics=clip['initial']
    samples=[];last={}
    for event in clip['events']:
        topic=event['topic'];clock=clip['originMs']+event['offsetMs']
        if topic!='Position.z':
            state.ingest(topic,event['payload'],clock_ms=clock)
            continue
        records=list(function_map[topic]([(None,event['payload'])],None))
        for r in records:
            number=str(r['DriverNo']);time=utc_ms(r.get('Utc'))
            timing=state.topics.get('TimingData',{}).get(number,{})
            sample={'driver':number,'time':time,'frameTime':clock,'x':r.get('X'),'y':r.get('Y'),
                    'lap':timing.get('NumberOfLaps'),'inPit':timing.get('InPit'),
                    'pitOut':timing.get('PitOut'),'status':r.get('Status')}
            if time is None or time<=last.get(number,-1):continue
            last[number]=time;samples.append(sample)
            if len(samples)>MAX_SAMPLES:raise ValueError('Sample limit exceeded; use a shorter window')
    return samples


def clean_laps(dataset):
    groups={};reasons={'invalid':0,'stale':0,'offTrack':0,'noLap':0,'pitLaps':0,'incompleteLaps':0,'outliers':0}
    for p in dataset['samples']:
        values=[p.get(k) for k in ('x','y','time')]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in values) or (p['x']==0 and p['y']==0):
            reasons['invalid']+=1;continue
        if abs(p['time']-p.get('frameTime',p['time']))>5000:
            reasons['stale']+=1;continue
        if str(p.get('status','')).lower() not in ('ontrack',''):
            reasons['offTrack']+=1;continue
        lap=p.get('lap')
        if lap is None or isinstance(lap,bool) or not str(lap).isdigit():reasons['noLap']+=1;continue
        key=f"{p.get('session',dataset.get('sessionPath','unknown'))}|{p['driver']}|{int(lap)}"
        groups.setdefault(key,[]).append(p)
    laps=[]
    for key,rows in groups.items():
        rows=sorted({r['time']:r for r in rows}.values(),key=lambda r:r['time'])
        if any(r.get('inPit') is True or r.get('pitOut') is True for r in rows):reasons['pitLaps']+=1;continue
        if len(rows)<45:reasons['incompleteLaps']+=1;continue
        points=np.array([[r['x'],r['y']] for r in rows]);times=np.array([r['time'] for r in rows])
        step=np.linalg.norm(np.diff(points,axis=0),axis=1)
        typical=np.median(step[step>0]) if np.any(step>0) else 0
        keep=np.ones(len(points),dtype=bool)
        for i in range(1,len(points)-1):
            if step[i-1]>typical*8 and step[i]>typical*8 and np.linalg.norm(points[i+1]-points[i-1])<min(step[i-1],step[i])*0.5:
                keep[i]=False;reasons['outliers']+=1
        points,times=points[keep],times[keep]
        diagonal=float(np.linalg.norm(np.ptp(points,axis=0)))
        duration=(times[-1]-times[0])/1000
        # Refuse partial laps or large missing sections. No line is invented
        # through a pit lane or a long GPS outage to make calibration succeed.
        if diagonal<=0 or not 40<=duration<=240 or np.max(np.diff(times))>2500 or np.linalg.norm(points[-1]-points[0])>diagonal*0.06:
            reasons['incompleteLaps']+=1;continue
        points=resample(points)
        laps.append({'id':key,'points':points,'driver':rows[0]['driver'],'duration':duration})
    return laps,reasons


def aligned_laps(laps):
    reference=laps[0]['points'];output=[reference]
    for lap in laps[1:]:
        points=lap['points']
        # Only adjust phase, never reverse driving direction.
        shifts=np.arange(-40,41)
        scores=[np.median(np.linalg.norm(np.roll(points,int(shift),axis=0)-reference,axis=1)) for shift in shifts]
        output.append(np.roll(points,int(shifts[int(np.argmin(scores))]),axis=0))
    return output


def build(dataset,svg,svg_path_id=None,threshold=0.015,layout='austin-livef1-v1'):
    if dataset.get('source')!='LiveF1' or dataset.get('schema')!='livef1-calibration-samples-v1':raise ValueError('Expected collected LiveF1 samples')
    laps,reasons=clean_laps(dataset)
    if len(laps)<3:raise ValueError(f'Need at least 3 complete non-pit laps (found {len(laps)}); rejection counts: {reasons}')
    laps=sorted(laps,key=lambda lap:lap['id'])
    holdout=laps[::3];training=[lap for i,lap in enumerate(laps) if i%3]
    arrays=aligned_laps(training)
    representative=np.median(np.stack(arrays),axis=0)
    representative=(np.roll(representative,1,axis=0)+2*representative+np.roll(representative,-1,axis=0))/4
    heldout=np.concatenate([lap['points'] for lap in holdout])
    validation=metrics(heldout,representative)
    original,path_id=sample_svg(svg,svg_path_id)
    fit=register_svg(original,representative)
    sim_error=max(fit['similarity'][key]['p95FractionOfDiagonal'] for key in ('trajectoryToOutline','outlineToTrajectory'))
    affine_error=max(fit['affine'][key]['p95FractionOfDiagonal'] for key in ('trajectoryToOutline','outlineToTrajectory'))
    decision='similarity-transform-sufficient' if sim_error<=threshold else 'affine-transform-candidate' if affine_error<=threshold else 'rebuild-from-gps-recommended'
    diagonal=float(np.linalg.norm(np.ptp(representative,axis=0)))
    points=[{'x':float(x),'y':float(y)} for x,y in representative]
    closed=points+[points[0]]
    return {'schema':'livef1-circuit-calibration-v1','circuitId':dataset['circuitId'],'layoutVersion':layout,
            'source':'LiveF1','status':'candidate','geometry':{'points':closed,'path':' '.join(f"{('M' if i==0 else 'L')} {p['x']:.6f} {p['y']:.6f}" for i,p in enumerate(closed))+' Z','coordinateSpace':'LiveF1-native','closed':True},
            'mapping':{'matrix':[1,0,0,1,0,0],'description':'Measured GPS trajectory and cars share native LiveF1 coordinates; display Y inversion is separate.'},
            'startFinish':{'at':0,'status':'timing-lap-boundary-inferred-unverified'},
            'annotations':{'corners':[],'sectors':[],'detectionPoints':[],'zones':[],'hotspots':[]},
            'validation':{'heldOut':validation,'thresholdFractionOfDiagonal':threshold,
                          'automaticChecksPassed':validation['p95FractionOfDiagonal']<=threshold,
                          'trainingLapIds':[lap['id'] for lap in training],'heldOutLapIds':[lap['id'] for lap in holdout],
                          'lapCount':len(laps),'driverCount':len(set(lap['driver'] for lap in laps)),
                          'rejected':reasons,'verified':False},
            'svgComparison':{'pathId':path_id,'svgSha256':hashlib.sha256(Path(svg).read_bytes()).hexdigest(),'decision':decision,**fit},
            'provenance':{'sessionPaths':dataset.get('sessionPaths',[dataset.get('sessionPath')]),'collectedSampleCount':len(dataset['samples']),
                          'createdAt':datetime.now(timezone.utc).isoformat(),'synthetic':bool(dataset.get('synthetic',False))},
            'debug':{'raw':[[p['x'],p['y']] for p in dataset['samples'][::max(1,len(dataset['samples'])//6000)] if all(isinstance(p.get(k),(int,float)) and np.isfinite(p[k]) for k in ('x','y'))],
                     'accepted':np.concatenate([lap['points'] for lap in holdout])[:6000].tolist(),
                     'originalSvg':original.tolist(),'diagonal':diagonal}}


def validate(calibration,dataset,confirm_visual=False,confirm_start=False):
    if dataset.get('source')!='LiveF1':raise ValueError('Validation must use LiveF1 samples')
    laps,reasons=clean_laps(dataset)
    excluded=set(calibration['validation']['trainingLapIds'])
    laps=[lap for lap in laps if lap['id'] not in excluded]
    if not laps:raise ValueError('No held-out laps; collect another calibration window')
    points=np.array([[p['x'],p['y']] for p in calibration['geometry']['points']])
    result=metrics(np.concatenate([lap['points'] for lap in laps]),points)
    passed=result['p95FractionOfDiagonal']<=calibration['validation']['thresholdFractionOfDiagonal']
    calibration['validation'].update(heldOut=result,automaticChecksPassed=passed,validationLapIds=[lap['id'] for lap in laps],rejected=reasons)
    verified=bool(passed and confirm_visual and confirm_start and not dataset.get('synthetic') and not calibration['provenance'].get('synthetic'))
    calibration['status']='verified' if verified else 'candidate'
    calibration['validation']['verified']=verified
    calibration['startFinish']['status']='visually-reviewed' if verified else 'timing-lap-boundary-inferred-unverified'
    return calibration


def select_session(year,meeting,session):
    matches=[s for s in list_sessions(year) if meeting.lower() in (s['label']+' '+s['path']).lower() and s['label'].split(' · ')[-1].lower()==session.lower()]
    if len(matches)!=1:raise ValueError('Select an unambiguous meeting/session using backend session listing')
    return matches[0]['path']


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    collect=commands.add_parser('collect');collect.add_argument('--year',type=int,default=2026);collect.add_argument('--meeting',default='Austin');collect.add_argument('--session',default='Race');collect.add_argument('--circuit',default='austin');collect.add_argument('--start',type=float,default=600);collect.add_argument('--duration',type=float,default=480);collect.add_argument('--clip',help='Use an existing bounded real LiveF1 clip instead of network');collect.add_argument('--output',required=True)
    generate=commands.add_parser('build');generate.add_argument('--samples',nargs='+',required=True);generate.add_argument('--svg',default='public/circuits/austin.svg');generate.add_argument('--svg-path-id');generate.add_argument('--layout-version',default='austin-livef1-v1');generate.add_argument('--threshold',type=float,default=0.015);generate.add_argument('--output',default='public/circuits/austin-calibration.json')
    check=commands.add_parser('validate');check.add_argument('--samples',required=True);check.add_argument('--calibration',default='public/circuits/austin-calibration.json');check.add_argument('--confirm-visual',action='store_true');check.add_argument('--confirm-start-finish',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='collect':
            clip=load_recording(args.clip) if args.clip else fetch_clip(select_session(args.year,args.meeting,args.session),args.start,args.duration)
            info=clip['initial'].get('SessionInfo',{})
            for event in clip['events']:
                if event['topic']=='SessionInfo':
                    from .protocol import merge
                    info=merge(info,event['payload'])
            short=info.get('Meeting',{}).get('Circuit',{}).get('ShortName','')
            normalized=re.sub(r'[^a-z0-9]','',short.lower())
            target=re.sub(r'[^a-z0-9]','',args.circuit.lower())
            aliases={'austin':{'austin','cota','circuitoftheamericas'}}
            if normalized not in aliases.get(target,{target}):
                raise ValueError('Archive circuit metadata does not match --circuit; choose the correct session')
            samples=collect_clip(clip)
            path=clip.get('sessionPath')
            for p in samples:p['session']=path
            data={'schema':'livef1-calibration-samples-v1','source':'LiveF1','circuitId':args.circuit,'sessionPath':path,'sessionPaths':[path],'circuitMetadata':info.get('Meeting',{}).get('Circuit',{}),'samples':samples}
            write_json(args.output,data)
            laps,reasons=clean_laps(data)
            print(json.dumps({'samples':len(samples),'completeNonPitLaps':len(laps),'rejected':reasons,'output':args.output},indent=2))
        elif args.command=='build':
            datasets=[read_json(p) for p in args.samples];data=dict(datasets[0]);data['samples']=[];data['sessionPaths']=[]
            for dataset in datasets:
                if dataset.get('circuitId')!=data.get('circuitId') or dataset.get('source')!='LiveF1':raise ValueError('Mixed circuit/source datasets')
                data['samples'].extend(dataset['samples']);data['sessionPaths'].extend(dataset.get('sessionPaths',[]));data['synthetic']=data.get('synthetic',False) or dataset.get('synthetic',False)
            if len(data['samples'])>MAX_SAMPLES:raise ValueError('Too many samples; choose fewer bounded clips')
            calibration=build(data,args.svg,args.svg_path_id,args.threshold,args.layout_version)
            write_json(args.output,calibration)
            print(json.dumps({'status':calibration['status'],'validation':calibration['validation'],'svgDecision':calibration['svgComparison']['decision'],'output':args.output},indent=2))
        else:
            calibration=validate(read_json(args.calibration),read_json(args.samples),args.confirm_visual,args.confirm_start_finish)
            write_json(args.calibration,calibration)
            print(json.dumps({'status':calibration['status'],'validation':calibration['validation']},indent=2))
    except Exception as exc:
        # Local errors are intentionally sanitized: upstream exceptions may include
        # account/HTTP details. No credentials or raw records are printed.
        if isinstance(exc,ValueError):print(f'Calibration not produced: {exc}')
        else:print('Calibration request failed. Check local authentication/network and input paths. No reference was replaced.')
        raise SystemExit(1) from None


if __name__=='__main__':main()
