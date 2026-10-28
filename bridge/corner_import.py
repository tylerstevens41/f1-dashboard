"""Offline FastF1 annotations; never modifies a LiveF1 calibration or race state."""
import argparse
import json
import math
from pathlib import Path

import numpy as np

SCHEMA = 'fastf1-circuit-source-v1'


class ImportFailure(ValueError):
    """Safe importer-generated message, never an upstream exception body."""



def normalize(rows):
    result = []
    for row in rows:
        number = int(row['Number'])
        if number < 1 or float(row['Number']) != number:
            raise ImportFailure('Invalid corner number')
        raw_letter=row.get('Letter')
        letter='' if raw_letter is None or isinstance(raw_letter,float) and math.isnan(raw_letter) else str(raw_letter).strip()
        if not letter.isalpha() and letter:
            raise ImportFailure('Invalid corner letter')
        item = dict(number=number, letter=letter, x=float(row['X']), y=float(row['Y']), angle=float(row['Angle']))
        if not all(math.isfinite(item[k]) for k in ('x', 'y', 'angle')):
            raise ImportFailure('Non-finite corner data')
        distance = row.get('Distance')
        item['distance'] = float(distance) if distance is not None and math.isfinite(float(distance)) else None
        result.append(item)
    if not result or len(result) > 100:
        raise ImportFailure('Missing or excessive FastF1 corners')
    if len({(p['number'], p['letter']) for p in result}) != len(result):
        raise ImportFailure('Duplicate corner identifiers')
    return result


def read(path):
    path = Path(path)
    if path.stat().st_size > 32*1024*1024:
        raise ImportFailure('Input exceeds 32 MiB')
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    if path.exists():
        raise ImportFailure(f'Refusing to overwrite {path}; choose a new output or remove the reviewed file first')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def fetch(year, event, session_name, cache, lap_collector=None):
    import fastf1
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    # Dedicated, disposable cache: cap storage between imports, not an entire season.
    def prune():
        files = sorted((p for p in cache.rglob('*') if p.is_file()), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for p in files:
            if total <= 512*1024*1024:
                break
            size=p.stat().st_size
            try:
                p.unlink()
            except PermissionError:
                continue  # Active Windows cache files must not break an import.
            total -= size
    prune()
    fastf1.Cache.enable_cache(str(cache))
    try:
        session = fastf1.get_session(year, event, session_name)
        session.load(telemetry=True, weather=False, messages=False)
        info = session.get_circuit_info()
        if info is None:
            raise ImportFailure('FastF1 returned no circuit information')
        lap = session.laps.pick_fastest()
        if lap is None:
            raise ImportFailure('No reference lap available')
        pos = lap.get_pos_data()[['X', 'Y']].dropna()
        if len(pos) < 100:
            raise ImportFailure('Insufficient reference-lap position data')
        result = {'schema': SCHEMA, 'year': year, 'event': event, 'session': session_name,
                'eventName': str(session.event.EventName), 'circuitKey': session.session_info['Meeting']['Circuit']['Key'],
                'provider': 'FastF1 / MultiViewer', 'fastf1Version': fastf1.__version__,
                'rotation': float(info.rotation), 'corners': normalize(info.corners.to_dict('records')),
                'reference': pos.to_numpy().astype(float).tolist(),
                'referenceLap': {'driver': str(lap.Driver), 'lap': int(lap.LapNumber)},
                'warning': 'Visualization markers are manually created and not highly accurate. Distance is telemetry-derived; marshal sectors are not timing sectors.'}
        if lap_collector is not None:
            result['boundaryLaps']=lap_collector(session)
        return result
    finally:
        prune()


def resample(points, count=256):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 4 or not np.isfinite(p).all():
        raise ImportFailure('Invalid track geometry')
    if np.linalg.norm(p[-1]-p[0]) > 1e-8:
        p = np.vstack([p, p[0]])
    length = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    if length[-1] <= 0:
        raise ImportFailure('Degenerate geometry')
    t = np.arange(count)/count*length[-1]
    return np.column_stack([np.interp(t, length, p[:, i]) for i in range(2)])


def similarity(source, target):
    a, b = source.mean(0), target.mean(0)
    x, y = source-a, target-b
    u, singular, vt = np.linalg.svd(x.T@y)
    matrix = (u@vt)*(singular.sum()/np.sum(x*x))
    return matrix, b-a@matrix


def register(source, target):
    """Ordered full-lap fit; test both directions and coordinate handedness.

    Odd samples are held out from each fit; remote near-equal alignments fail.
    """
    raw=np.asarray(source,dtype=float)
    if np.linalg.norm(raw[0]-raw[-1]) > np.linalg.norm(np.ptp(raw,axis=0))*.05:
        raise ImportFailure('Reference telemetry does not cover a complete lap')
    a, b = resample(source), resample(target)
    candidates = []
    for direction in (1, -1):
        for shift in range(len(b)):
            correspondence = b[(shift+direction*np.arange(len(b))) % len(b)]
            matrix, translation = similarity(a[::2], correspondence[::2])
            error = np.linalg.norm(a@matrix+translation-correspondence, axis=1)
            candidates.append((float(np.sqrt(np.mean(error[1::2]**2))), direction, shift, matrix, translation, float(np.percentile(error[1::2], 95))))
    candidates.sort(key=lambda x: x[0])
    best = candidates[0]
    diag = float(np.linalg.norm(np.ptp(np.asarray(target), axis=0)))
    remote = [c for c in candidates if c[1] != best[1] or min(abs(c[2]-best[2]), 256-abs(c[2]-best[2])) > 12]
    if best[0] > diag*.015 or best[5] > diag*.03:
        raise ImportFailure(f'Alignment rejected: held-out RMS {best[0]:.2f}, p95 {best[5]:.2f}, extent {diag:.2f}')
    if remote and remote[0][0] <= max(best[0]*1.25, diag*.001):
        raise ImportFailure('Ambiguous full-lap alignment; use independently established control points')
    return best, diag


def project_corner(point, target, extent):
    p = np.asarray(target, dtype=float)
    delta = np.diff(p, axis=0)
    sizes = np.linalg.norm(delta, axis=1)
    t = np.clip(np.sum((point-p[:-1])*delta, axis=1)/np.maximum(sizes**2, 1e-12), 0, 1)
    error = np.linalg.norm(p[:-1]+t[:, None]*delta-point, axis=1)
    distance = np.r_[0, np.cumsum(sizes)]
    fractions = (distance[:-1]+t*sizes)/distance[-1]
    i = int(np.argmin(error))
    separation = np.minimum(abs(fractions-fractions[i]), 1-abs(fractions-fractions[i]))
    others = error[separation > .025]
    if error[i] > extent*.025:
        raise ImportFailure(f'Corner is too far from the calibrated path ({error[i]:.2f})')
    if len(others) and float(others.min())-float(error[i]) < extent*.003:
        raise ImportFailure('Ambiguous corner near multiple track sections')
    return float(fractions[i] % 1), float(error[i])


def geometry_id(points):
    # Match createGeometry padding/Y orientation and JS fingerprint exactly.
    p = np.asarray(points, dtype=float)
    projected = np.column_stack([p[:, 0]-p[:, 0].min()+650, p[:, 1].max()-p[:, 1]+650])
    text = ';'.join(f'{x:.3f},{y:.3f}' for x, y in projected)
    hash_value = 2166136261
    for ch in text:
        hash_value = ((hash_value ^ ord(ch))*16777619) & 0xffffffff
    return format(hash_value, 'x')


def align(source, calibration, circuit, layout):
    if source.get('schema') != SCHEMA or not source.get('corners'):
        raise ImportFailure('Missing FastF1 source data')
    if calibration.get('schema') != 'livef1-circuit-calibration-v1' or calibration.get('source') != 'LiveF1' or calibration.get('circuitId') != circuit or calibration.get('layoutVersion') != layout:
        raise ImportFailure('Calibration circuit/layout/source mismatch')
    points = [[p['x'], p['y']] for p in calibration['geometry']['points']]
    target = np.asarray(points, dtype=float)
    if np.linalg.norm(target[0]-target[-1]) > .01:
        raise ImportFailure('Calibration must contain a closed lap')
    if source.get('circuitId') != circuit or source.get('layoutVersion') != layout:
        raise ImportFailure('FastF1 source circuit/layout mismatch')
    best, extent = register(source['reference'], target)
    rms, direction, shift, matrix, translation, p95 = best
    corners = []
    label_positions = []
    for original in source['corners']:
        p = np.array([original['x'], original['y']])@matrix+translation
        fraction, error = project_corner(p, target, extent)
        angle = math.radians(original['angle'])
        offset = np.array([math.cos(angle), math.sin(angle)])@matrix
        offset = offset/np.linalg.norm(offset)*450
        # Prefer the side away from the rest of the path; keep labels separated.
        # These cosmetic offsets never change the measured anchor or GPS mapping.
        def clearance(label):
            a=target[:-1];delta=np.diff(target,axis=0)
            t=np.clip(np.sum((label-a)*delta,axis=1)/np.maximum(np.sum(delta*delta,axis=1),1e-12),0,1)
            return float(np.linalg.norm(a+t[:,None]*delta-label,axis=1).min())
        if clearance(p-offset)>clearance(p+offset):
            offset=-offset
        for _ in range(6):
            if not any(np.linalg.norm(p+offset-q)<340 for q in label_positions):
                break
            offset*=1.25
        label_positions.append(p+offset)
        corners.append({'number': original['number'], 'letter': original['letter'], 'at': fraction,
                        'offset': {'x': float(offset[0]), 'y': float(-offset[1])}, 'status': 'provisional',
                        'imported': True, 'alignmentError': error, 'source': original})
    # Numbered turns must traverse one lap in order, not leap across hairpins.
    deltas = [(direction*(b['at']-a['at'])) % 1 for a, b in zip(corners, corners[1:])]
    if deltas and (max(deltas) > .35 or sum(deltas) >= 1):
        raise ImportFailure('Corner order is inconsistent with the registered driving direction')
    return {'schema': 'f1-circuit-annotations-v1', 'circuitId': circuit, 'layoutVersion': layout,
            'geometryId': geometry_id(points), 'direction': direction, 'startFinish': None,
            'sector1End': None, 'sector2End': None, 'corners': corners, 'zones': [], 'detectionPoints': [],
            'speedTraps': [], 'pitLane': None, 'provenance': f"FastF1 / MultiViewer {source['year']} {source['event']}; registered to local LiveF1 geometry; UNVERIFIED",
            'importSource': source, 'alignment': {'status': 'provisional', 'heldOutRms': rms, 'heldOutP95': p95,
                'extent': extent, 'direction': direction, 'shift': shift, 'matrix': matrix.tolist(), 'translation': translation.tolist(),
                'rotationMetadata': source['rotation'], 'method': 'ordered cyclic similarity fit; independent odd samples; corner ambiguity and order gates'}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--year', type=int, default=2026)
    p.add_argument('--event', default='United States')
    p.add_argument('--session', default='R')
    p.add_argument('--circuit', default='austin')
    p.add_argument('--layout', default='austin-livef1-v1')
    p.add_argument('--cache', default='data-cache/fastf1')
    p.add_argument('--source-input')
    p.add_argument('--source-output')
    p.add_argument('--calibration')
    p.add_argument('--output')
    p.add_argument('--with-sectors',action='store_true',help='Also calculate start/finish and sectors from multi-lap timing/GPS')
    args = p.parse_args()
    try:
        if not args.source_output and not args.output:
            raise ImportFailure('Specify --source-output and/or --output')
        collector=None
        if args.with_sectors:
            from .sector_import import collect_laps, add_boundaries
            collector=collect_laps
        source = read(args.source_input) if args.source_input else fetch(args.year, args.event, args.session, args.cache, lap_collector=collector)
        if not args.source_input:
            source.update(circuitId=args.circuit, layoutVersion=args.layout)
        if args.source_output:
            write(args.source_output, source)
        if args.output:
            if not args.calibration or Path(args.output).resolve() == Path(args.calibration).resolve():
                raise ImportFailure('A separate existing --calibration is required; it is never overwritten')
            calibration=read(args.calibration)
            result = align(source, calibration, args.circuit, args.layout)
            if args.with_sectors:result=add_boundaries(source,result,calibration)
            write(args.output, result)
            print(f"Imported {len(result['corners'])} provisional corners; alignment {result['alignment']}")
    except ImportFailure as exc:
        p.exit(1, f'Corner import failed: {exc}\n')
    except Exception as exc:
        p.exit(1, f'Corner import failed ({type(exc).__name__}). Check local FastF1 data availability/authentication; no annotation output was generated.\n')


if __name__ == '__main__':
    main()
