"""Offline multi-lap timing/GPS boundaries; uses only the FastF1 environment."""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from .corner_import import ImportFailure, align, fetch, project_corner, read, write

KEYS = ('startFinish', 'sector1End', 'sector2End')


def interpolate(samples, when, max_gap=.5):
    """Times are seconds on the session clock, never sliced telemetry Time."""
    p = np.asarray(samples, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < 2 or not np.isfinite(p).all():
        raise ImportFailure('invalid-position-data')
    if np.any(np.diff(p[:, 0]) <= 0):
        raise ImportFailure('nonmonotonic-position-times')
    i = int(np.searchsorted(p[:, 0], when, side='right'))
    if i == 0 or i == len(p):
        raise ImportFailure('unbracketed-crossing')
    a, b = p[i-1], p[i]
    if b[0]-a[0] > max_gap:
        raise ImportFailure('crossing-gps-gap')
    t = (when-a[0])/(b[0]-a[0])
    return a[1:]+t*(b[1:]-a[1:]), float(b[0]-a[0])


def crossing_times(lap):
    fields = ['start', 'end', 'lapTime', 's1', 's2', 's3']
    if any(not isinstance(lap.get(k), (int, float)) or not np.isfinite(lap[k]) for k in fields):
        raise ImportFailure('missing-timing')
    if not lap.get('accurate') or lap.get('pit') or lap.get('generated') or lap.get('deleted'):
        raise ImportFailure('invalid-or-pit-lap')
    if lap.get('trackStatus') not in ('1', '2', '12', '21'):
        raise ImportFailure('interrupted-lap')
    if min(lap[k] for k in ('lapTime', 's1', 's2', 's3')) <= 0:
        raise ImportFailure('invalid-duration')
    if abs(lap['s1']+lap['s2']+lap['s3']-lap['lapTime']) > .0031 or abs(lap['end']-lap['start']-lap['lapTime']) > .05:
        raise ImportFailure('inconsistent-lap-clock')
    if not lap.get('clockChecked'):
        raise ImportFailure('unchecked-date-session-clock')
    return [lap['start'], lap['start']+lap['s1'], lap['start']+lap['s1']+lap['s2'], lap['end']]


def collect_laps(session, limit=40):
    """Bounded original samples, padded using the full driver stream at lap edges."""
    import pandas as pd
    def seconds(value):
        return None if pd.isna(value) else float(value.total_seconds())
    result, rejected = [], Counter()
    # Round-robin race laps across drivers, rather than only the fastest driver.
    rows = session.laps.sort_values(['LapNumber', 'DriverNumber'])
    for _, row in rows.iterrows():
        if len(result) >= limit:
            break
        try:
            lap = {'driver': str(row.DriverNumber), 'lap': int(row.LapNumber),
                   'start': seconds(row.LapStartTime), 'end': seconds(row.Time),
                   'lapTime': seconds(row.LapTime), 's1': seconds(row.Sector1Time),
                   's2': seconds(row.Sector2Time), 's3': seconds(row.Sector3Time),
                   'accurate': False if pd.isna(row.IsAccurate) else bool(row.IsAccurate),
                   'pit': not pd.isna(row.PitInTime) or not pd.isna(row.PitOutTime),
                   'generated': pd.isna(row.FastF1Generated) or bool(row.FastF1Generated),
                   'deleted': False if pd.isna(row.get('Deleted')) else bool(row.get('Deleted')),
                   'trackStatus': str(row.TrackStatus), 'clockChecked': True}
            crossing_times(lap)
            pos = session.pos_data[lap['driver']]
            pos = pos[(pos.SessionTime.dt.total_seconds() >= lap['start']-1) &
                      (pos.SessionTime.dt.total_seconds() <= lap['end']+1)]
            # No merged/resampled telemetry or interpolated edge samples.
            if len(pos) < 100 or (pos.Source != 'pos').any() or (pos.Status != 'OnTrack').any():
                raise ImportFailure('invalid-original-position-data')
            if not np.isfinite(pos[['X', 'Y']].to_numpy(dtype=float)).all() or ((pos.X==0)&(pos.Y==0)).any() or pos.Date.isna().any() or pos.SessionTime.isna().any():
                raise ImportFailure('invalid-position-data')
            discrepancy = ((pos.Date-session.t0_date)-pos.SessionTime).dt.total_seconds().abs()
            if discrepancy.max() > .002 or pd.isna(row.LapStartDate) or abs((row.LapStartDate-session.t0_date).total_seconds()-lap['start']) > .002:
                raise ImportFailure('date-session-clock-mismatch')
            times = pos.SessionTime.dt.total_seconds().to_numpy()
            if len(times) < 2 or np.any(np.diff(times) <= 0) or np.max(np.diff(times)) > .75:
                raise ImportFailure('lap-gps-gap')
            if np.any(np.linalg.norm(np.diff(pos[['X','Y']].to_numpy(dtype=float),axis=0),axis=1)/np.diff(times)>2000):
                raise ImportFailure('position-spike')
            lap['positions'] = np.column_stack([times, pos.X, pos.Y]).astype(float).tolist()
            for crossing in crossing_times(lap):interpolate(lap['positions'],crossing)
            # Feed sector SessionTime fields may include delivery delays: report,
            # never substitute their receipt times for duration-based crossings.
            lap['timingReceiptOffsets'] = [None if seconds(row.get(k)) is None else seconds(row.get(k))-when
                for k, when in zip(('Sector1SessionTime','Sector2SessionTime','Sector3SessionTime'), crossing_times(lap)[1:])]
            result.append(lap)
        except ImportFailure as exc:
            rejected[str(exc)] += 1
        except (KeyError, TypeError, ValueError, AttributeError):
            rejected['missing-lap-or-position-fields'] += 1
    return {'schema': 'fastf1-boundary-laps-v1', 'timeBasis': 'SessionTime-seconds; Date checked against session.t0_date',
            'laps': result, 'rejected': dict(rejected), 'limit': limit, 'inspected': len(result)+sum(rejected.values())}


def circular_median(values, minimum=5):
    values = np.asarray(values, dtype=float)
    if len(values) < minimum or not np.isfinite(values).all():
        raise ImportFailure('Not enough valid crossing estimates (need at least five laps)')
    delta = lambda x: (x+.5) % 1-.5
    anchor = values[np.argmin(np.sum(np.abs(delta(values[:, None]-values)), axis=1))]
    offsets = delta(values-anchor)
    center = np.median(offsets)
    mad = np.median(np.abs(offsets-center))
    keep = np.abs(offsets-center) <= min(.01, max(.001, 4*1.4826*mad))
    if keep.sum() < minimum:
        raise ImportFailure('Too few estimates after circular outlier rejection')
    median = float((anchor+np.median(offsets[keep])) % 1)
    spread = float(np.percentile(np.abs(delta(values[keep]-median)), 95))
    if spread > .005:
        raise ImportFailure('Crossing estimates disagree (p95 exceeds 0.5% of lap)')
    return median, {'accepted': int(keep.sum()), 'outliers': int((~keep).sum()), 'p95LapFraction': spread}


def fia_check(result):
    """Coarse independent map checks, never force GPS fractions to FIA distances."""
    if result['circuitId'] != 'austin' or result['sectorSource']['year'] != 2026:
        return {'status': 'unavailable', 'warnings': ['No event-specific reference configured']}
    direction = result['direction']
    s, a, b = [result[k]['at'] for k in KEYS]
    lengths = [((y-x)*direction) % 1*5513 for x, y in ((s,a),(a,b),(b,s))]
    warnings, checks = [], []
    for i, (estimated, official) in enumerate(zip(lengths, (1914,1941,1658))):
        checks.append({'sector': i+1, 'geometryRatioScaledMetres': estimated, 'fiaMetres': official})
        if abs(estimated-official) > official*.10:
            warnings.append(f'Sector {i+1} racing-line ratio differs from FIA distance by over 10%')
    corners = {c['number']: c for c in result['corners'] if not c.get('letter')}
    for number, boundary in ((7,a),(13,b)):
        if number not in corners:
            warnings.append(f'T{number} reference unavailable')
            continue
        distance = ((corners[number]['at']-boundary)*direction) % 1*5513
        checks.append({'beforeTurn': number, 'geometryRatioScaledMetres': distance, 'fiaMetres':65})
        if abs(distance-65)>100:
            warnings.append(f'Intermediate before T{number} disagrees with the FIA map')
    if 20 in corners and 1 in corners:
        gap = ((corners[1]['at']-corners[20]['at'])*direction) % 1
        if ((s-corners[20]['at'])*direction) % 1 >= gap:
            warnings.append('Timing finish is not between T20 and T1')
    else:
        warnings.append('Finish reference turns unavailable')
    return {'status': 'discrepancy' if warnings else 'coarsely-consistent-unverified', 'checks': checks, 'warnings': warnings,
            'note': 'Racing-line ratios and FastF1 visualization turns are approximate, not surveyed timing lines. Confirm the lap control line, not the separate grid start line, on the FIA map.',
            'reference': 'https://www.fia.com/system/files/decision-document/2026_united_states_grand_prix_-_competition_notes_-_circuit_map_pit_lane_drawing_and_emergency_exits_map.pdf'}


def add_boundaries(source, result, calibration):
    data = source.get('boundaryLaps')
    if not data or data.get('schema') != 'fastf1-boundary-laps-v1':
        raise ImportFailure('Cached source lacks checked multi-lap timing/GPS; fetch with --with-sectors or sector_import')
    target = np.array([[p['x'],p['y']] for p in calibration['geometry']['points']], dtype=float)
    matrix = np.array(result['alignment']['matrix']); translation = np.array(result['alignment']['translation'])
    estimates = {k: [] for k in KEYS}; lap_details = []; rejected = Counter(data.get('rejected', {}))
    seen=set()
    for lap in data['laps']:
        try:
            identity=(lap.get('driver'),lap.get('lap'),lap.get('start'),lap.get('end'))
            if identity in seen:raise ImportFailure('duplicate-lap')
            seen.add(identity)
            when = crossing_times(lap)
            positions = [interpolate(lap['positions'], t) for t in when]
            projected = [project_corner(p@matrix+translation,target,result['alignment']['extent']) for p,_ in positions]
            direction = result['direction']
            finish_diff = (projected[3][0]-projected[0][0]+.5) % 1-.5
            if abs(finish_diff) > .005:
                raise ImportFailure('lap-start-end-disagreement')
            finish = (projected[0][0]+finish_diff/2) % 1
            fractions = [finish, projected[1][0], projected[2][0]]
            distances = [((fractions[1]-finish)*direction)%1, ((fractions[2]-finish)*direction)%1]
            if not .1<distances[0]<distances[1]<.9 or distances[1]-distances[0]<.1:
                raise ImportFailure('invalid-boundary-order')
            for k,f in zip(KEYS,fractions): estimates[k].append(f)
            lap_details.append({'driver':lap['driver'],'lap':lap['lap'],'fractions':fractions,
                                'startAt':projected[0][0],'endAt':projected[3][0],
                                'projectionErrors':[e for _,e in projected], 'bracketSeconds':[gap for _,gap in positions]})
        except ImportFailure as exc: rejected[str(exc)] += 1
    if len(lap_details)<5:raise ImportFailure(f'Only {len(lap_details)} usable laps; need five. Rejected: {dict(rejected)}')
    for k, values in estimates.items():
        try:
            fraction, stats = circular_median(values)
        except ImportFailure as exc:
            raise ImportFailure(f'{k}: {exc}; {len(lap_details)} candidate laps; rejected: {dict(rejected)}') from exc
        stats['p95NativeDistance']=stats['p95LapFraction']*float(np.linalg.norm(np.diff(target,axis=0),axis=1).sum())
        result[k] = {'at':fraction, 'status':'provisional', 'calculated':True,
                     'sourceEstimate': {'at':fraction,'statistics':stats}, 'label': {'startFinish':'START / FINISH','sector1End':'S1','sector2End':'S2'}[k]}
    s,a,b = [result[k]['at'] for k in KEYS]
    d1,d2 = ((a-s)*result['direction'])%1, ((b-s)*result['direction'])%1
    if not .1<d1<d2<.9 or d2-d1<.1: raise ImportFailure('Aggregated boundaries have invalid lap order')
    result['sectorSource'] = {k:source[k] for k in ('year','event','session')}
    result['boundaryDiagnostics'] = {'status':'provisional','analyzed':len(data['laps'])+sum(data.get('rejected',{}).values()),
        'validLaps':len(lap_details),'drivers':len({p['driver'] for p in lap_details}), 'rejected':dict(rejected),
        'estimates':lap_details,'timeBasis':data.get('timeBasis'), 'registration':result['alignment']}
    result['boundaryDiagnostics']['fia'] = fia_check(result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--year',type=int,default=2026);p.add_argument('--event',default='United States');p.add_argument('--session',default='R')
    p.add_argument('--circuit',default='austin');p.add_argument('--layout',default='austin-livef1-v1')
    p.add_argument('--cache',default='data-cache/fastf1');p.add_argument('--source-input');p.add_argument('--source-output')
    p.add_argument('--calibration');p.add_argument('--output')
    args=p.parse_args()
    try:
        if not args.source_output and not args.output:raise ImportFailure('Specify --source-output or --output')
        source=read(args.source_input) if args.source_input else fetch(args.year,args.event,args.session,args.cache,lap_collector=collect_laps)
        if not args.source_input:source.update(circuitId=args.circuit,layoutVersion=args.layout)
        if args.source_output:write(args.source_output,source)
        if args.output:
            if not args.calibration or Path(args.calibration).resolve()==Path(args.output).resolve():raise ImportFailure('A separate calibration input is required')
            calibration=read(args.calibration)
            result=add_boundaries(source,align(source,calibration,args.circuit,args.layout),calibration)
            # Dedicated boundary file never replaces the user's imported corners.
            result['corners']=[]
            write(args.output,result)
            print({k:result[k]['at'] for k in KEYS});print(result['boundaryDiagnostics'])
    except ImportFailure as exc:p.exit(1,f'Sector import failed: {exc}\n')
    except Exception as exc:p.exit(1,f'Sector import failed ({type(exc).__name__}); check local data availability.\n')


if __name__=='__main__':main()
