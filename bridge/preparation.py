"""On-demand/serial batch LiveF1 circuit preparation. No FastF1 import here."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / 'circuit-assets'
STAGES = ('lookup', 'collecting', 'geometry', 'corners', 'sectors', 'ready')


class PreparationError(ValueError):
    """Only coordinator-generated, credential-safe messages reach the browser."""


def slug(value):
    result = re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-')
    if not result or len(result) > 100:
        raise PreparationError('Missing or invalid circuit identity')
    return result


def identity(session):
    circuit = session.get('circuit') or {}
    key = circuit.get('Key')
    name = circuit.get('ShortName')
    if key is None or not name:
        raise PreparationError('Archive metadata has no stable circuit key/name; cannot guess its layout')
    year = int(session['year'])
    if not 2018 <= year <= 2100:
        raise PreparationError('Unsupported season')
    # Same-season sessions share a candidate layout. No silent cross-season reuse.
    identifier = 'austin' if slug(name) in ('austin', 'cota', 'circuit-of-the-americas') else slug(name)
    layout = f'{identifier}-{year}-livef1-v1'
    return {'id': identifier, 'name': str(name), 'circuitKey': str(key), 'year': year,
            'layoutVersion': layout, 'assetKey': f'circuit-{slug(key)}-{year}',
            'event': session['event'], 'session': session['session'], 'path': session['path']}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, allow_nan=False, separators=(',', ':'))
    if len(text) > 16*1024*1024:
        raise PreparationError('Prepared asset exceeds 16 MiB')
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 16*1024*1024:
        raise PreparationError('Asset too large')
    return json.loads(path.read_text(encoding='utf8'))


def validate_bundle(bundle, expected=None):
    from .corner_import import geometry_id
    from .calibration_math import metrics
    import numpy as np
    if bundle.get('schema') != 'prepared-circuit-v1' or bundle.get('toolVersion') != VERSION:
        raise PreparationError('Unsupported prepared circuit version')
    meta = bundle['identity']
    if expected and any(meta.get(k) != expected.get(k) for k in ('assetKey', 'circuitKey', 'year', 'layoutVersion')):
        raise PreparationError('Circuit/layout/season mismatch')
    calibration = bundle['calibration']
    if calibration.get('source') != 'LiveF1' or calibration.get('circuitId') != meta['id'] or calibration.get('layoutVersion') != meta['layoutVersion']:
        raise PreparationError('Calibration identity mismatch')
    points = calibration['geometry']['points']
    xy = np.array([[p['x'], p['y']] for p in points], dtype=float)
    matrix = calibration['mapping']['matrix']
    if len(xy) < 45 or len(xy) > 4096 or not np.isfinite(xy).all() or np.linalg.norm(xy[0]-xy[-1]) > .01 or len(matrix) != 6 or not np.isfinite(matrix).all():
        raise PreparationError('Invalid closed geometry/mapping')
    if abs(matrix[0]*matrix[3]-matrix[1]*matrix[2]) < 1e-12:
        raise PreparationError('Degenerate mapping')
    if not calibration['validation'].get('automaticChecksPassed') or calibration['provenance'].get('synthetic'):
        raise PreparationError('Geometry has not passed real-data preparation checks')
    # Also reject a degenerate extent before serving any positions.
    if not np.isfinite(metrics(xy, xy)['p95FractionOfDiagonal']):
        raise PreparationError('Degenerate geometry')
    fingerprint = geometry_id(xy)
    if bundle.get('geometryId') != fingerprint:
        raise PreparationError('Geometry fingerprint mismatch')
    for field in ('corners', 'sectors'):
        annotation = bundle.get(field)
        if annotation is None:
            continue
        if annotation.get('schema') != 'f1-circuit-annotations-v1' or annotation.get('geometryId') != fingerprint or annotation.get('circuitId') != meta['id'] or annotation.get('layoutVersion') != meta['layoutVersion'] or annotation.get('direction') != 1:
            raise PreparationError('Annotation geometry/identity/direction mismatch')
        def valid_at(value):
            return isinstance(value,(int,float)) and not isinstance(value,bool) and np.isfinite(value) and 0 <= value < 1
        corners = annotation.get('corners')
        if not isinstance(corners,list) or any(not isinstance(c,dict) or not valid_at(c.get('at')) or not isinstance(c.get('number'),int) or c['number']<1 for c in corners):
            raise PreparationError('Invalid corner annotations')
        values = [annotation.get(k) for k in ('startFinish','sector1End','sector2End')]
        if any(v is not None and (not isinstance(v,dict) or not valid_at(v.get('at')) or v.get('status') not in ('provisional','verified')) for v in values):
            raise PreparationError('Invalid boundary annotations')
        if all(values):
            start,a,b = [v['at'] for v in values]
            if not 0 < (a-start)%1 < (b-start)%1 < 1:
                raise PreparationError('Invalid boundary lap order')
    if bundle.get('complete') and (not (bundle.get('corners') or {}).get('corners') or not all((bundle.get('sectors') or {}).get(k) for k in ('startFinish','sector1End','sector2End'))):
        raise PreparationError('Complete asset is missing required annotations')
    return bundle


def process_alive(pid):
    if pid <= 0:
        return True  # unknown owner: do not steal
    if os.name == 'nt':
        # os.kill(pid, 0) can terminate a process on Windows. Query only.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # invalid PID vs access denied
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


class AssetStore:
    def __init__(self, root=DEFAULT_STORE):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, key):
        if not re.fullmatch(r'circuit-[a-z0-9-]+-20\d\d', key):
            raise PreparationError('Invalid asset key')
        return self.root / key

    def get(self, meta):
        pointer = self.directory(meta['assetKey']) / 'current.json'
        if not pointer.exists():
            return None
        revision = read_json(pointer)['revision']
        if not re.fullmatch(r'[0-9a-f]{32}', revision):
            raise PreparationError('Invalid asset revision')
        return validate_bundle(read_json(pointer.parent / f'{revision}.json'), meta)

    def lookup(self, year, path=None, circuit_key=None):
        matches = []
        for pointer in self.root.glob(f'circuit-*-{int(year)}/current.json'):
            try:
                revision = read_json(pointer)['revision']
                if not re.fullmatch(r'[0-9a-f]{32}', revision):
                    continue
                candidate = validate_bundle(read_json(pointer.parent / f'{revision}.json'))
                meta = candidate['identity']
                if meta['year'] == int(year) and ((path and meta['path'] == path) or
                        (not path and circuit_key is not None and meta['circuitKey'] == str(circuit_key))):
                    matches.append(candidate)
            except (ValueError, KeyError, OSError):
                continue  # corrupted assets are never served as valid geometry
        return matches[0] if len(matches) == 1 else None

    def publish(self, bundle):
        validate_bundle(bundle)
        directory = self.directory(bundle['identity']['assetKey'])
        # Immutable revisions retain previous reviewed/manual outputs. No public/
        # files or browser settings are ever written by this coordinator.
        revision = uuid.uuid4().hex
        atomic_json(directory / f'{revision}.json', bundle)
        atomic_json(directory / 'current.json', {'revision': revision})
        return bundle

    def progress(self, meta, **value):
        record = {'identity': meta, 'updatedAt': time.time(), **value}
        atomic_json(self.directory(meta['assetKey']) / 'job.json', record)
        return record

    def acquire(self, meta):
        directory = self.directory(meta['assetKey'])
        directory.mkdir(parents=True, exist_ok=True)
        lock = directory / '.lock'
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w') as handle:
                    handle.write(str(os.getpid()))
                return lock
            except FileExistsError:
                try:
                    pid = int(lock.read_text())
                    if not process_alive(pid):
                        lock.unlink(missing_ok=True)  # crashed process; immutable pointer is intact
                        continue
                except (ValueError, PermissionError, OSError):
                    pass  # uncertain owner: never steal an active/unknown lock
                raise PreparationError('Circuit preparation already running in another process')
        raise PreparationError('Could not acquire preparation lock')


def prune_cache(root, limit=128*1024*1024):
    root = Path(root)
    files = sorted((p for p in root.glob('*.json.gz') if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= limit:
            break
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        total -= size


def collect_geometry(meta, cache, report, windows=(5400, 6000, 3600)):
    from .archive import fetch_clip
    from .calibrate import collect_clip, clean_laps, build, read_json as read_samples, write_json
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    failures = []
    for offset in windows:
        try:
            report(stage='collecting', state='preparing', windowStart=offset)
            token = hashlib.sha256(f"{meta['path']}:{offset}:480".encode()).hexdigest()
            file = cache / f'{token}.json.gz'
            if file.exists():
                data = read_samples(file)
            else:
                clip = fetch_clip(meta['path'], offset, 480)
                data = {'schema': 'livef1-calibration-samples-v1', 'source': 'LiveF1', 'circuitId': meta['id'],
                        'sessionPath': meta['path'], 'sessionPaths': [meta['path']], 'samples': collect_clip(clip)}
                info = clip['initial'].get('SessionInfo', {})
                for event in clip['events']:
                    if event['topic'] == 'SessionInfo':
                        from .protocol import merge
                        info = merge(info, event['payload'])
                if str(info.get('Meeting', {}).get('Circuit', {}).get('Key')) != meta['circuitKey']:
                    raise PreparationError('Archive GPS circuit identity mismatch')
                write_json(file, data)
            if data.get('circuitId') != meta['id'] or data.get('sessionPath') != meta['path']:
                raise PreparationError('Cached GPS source identity mismatch')
            laps, rejected = clean_laps(data)
            if len(laps) < 3:
                failures.append({'offset': offset, 'completeLaps': len(laps), 'rejected': rejected})
                continue
            report(stage='geometry', state='preparing')
            import numpy as np
            areas = [float(np.sum(lap['points'][:,0]*np.roll(lap['points'][:,1],-1)-np.roll(lap['points'][:,0],-1)*lap['points'][:,1])) for lap in laps]
            if any(abs(area)<1e-6 for area in areas) or len({bool(area>0) for area in areas}) != 1:
                failures.append({'offset':offset,'reason':'inconsistent driving direction or degenerate loop'})
                continue
            result = build(data, layout=meta['layoutVersion'])
            if not result['validation']['automaticChecksPassed']:
                failures.append({'offset': offset, 'reason': 'held-out geometry error'})
                continue
            # Retain a diagnostic failure, not a manufactured outline, if the
            # sampled lap has an unreasonably long spatial jump after resampling.
            xy = np.array([[p['x'], p['y']] for p in result['geometry']['points']])
            if np.max(np.linalg.norm(np.diff(xy, axis=0), axis=1)) > np.linalg.norm(np.ptp(xy, axis=0))*.04:
                failures.append({'offset': offset, 'reason': 'incomplete spatial coverage'})
                continue
            result.pop('debug', None)
            result['provenance']['preparationWindowSeconds'] = offset
            return result
        except PreparationError:
            raise
        except Exception:
            failures.append({'offset': offset, 'reason': 'source unavailable or insufficient complete on-track laps'})
        finally:
            prune_cache(cache)
    raise PreparationError(f'No reliable geometry in {len(windows)} bounded windows. Try another session or --windows. Diagnostics: {failures}')


def fast_python():
    configured = os.environ.get('F1_FASTF1_PYTHON')
    return Path(configured) if configured else ROOT / '.venv-fastf1' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def import_annotations(meta, calibration, root, report, runner=subprocess.run):
    executable = fast_python()
    if not executable.is_file():
        return None, None, ['FastF1 environment missing. Create .venv-fastf1 from bridge/requirements-corners.txt or set F1_FASTF1_PYTHON.']
    with tempfile.TemporaryDirectory(prefix='f1-import-', dir=root) as temp:
        temp = Path(temp)
        atomic_json(temp / 'calibration.json', calibration)
        request = {'identity': meta, 'calibration': str(temp / 'calibration.json'), 'output': str(temp / 'result.json'),
                   'cache': str(Path(root) / 'fastf1-cache'), 'sourceCache': str(Path(root) / 'annotation-sources')}
        atomic_json(temp / 'request.json', request)
        report(stage='corners', state='preparing')
        try:
            result = runner([str(executable), '-m', 'bridge.preparation_worker', '--request', str(temp / 'request.json')],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600, check=False)
            if result.returncode != 0:
                raise PreparationError('Offline annotation process failed; check .venv-fastf1 and historical data availability')
            output = read_json(temp / 'result.json')
            report(stage='sectors', state='preparing')
            return output.get('corners'), output.get('sectors'), output.get('warnings', [])
        except subprocess.TimeoutExpired:
            return None, None, ['FastF1 annotation preparation exceeded 10 minutes; geometry retained. Retry locally.']
        except (OSError, ValueError):
            return None, None, ['FastF1 annotation preparation failed; geometry retained. Check environment and source availability.']


def prepare(session, store=None, report=lambda **_: None, retry=True, windows=(5400, 6000, 3600), collector=collect_geometry, importer=import_annotations):
    from .corner_import import geometry_id
    store = store or AssetStore()
    meta = identity(session)
    def progress(**value):
        record = store.progress(meta, **value)
        report(**record)
    existing = store.get(meta)
    if existing and (not retry or existing.get('complete')):
        progress(stage='ready', state='ready', cached=True, complete=existing['complete'])
        return existing
    lock = store.acquire(meta)
    try:
        progress(stage='lookup', state='preparing')
        calibration = copy.deepcopy(existing['calibration']) if existing else collector(meta, store.root / 'gps-cache', progress, windows=windows)
        points = [[p['x'], p['y']] for p in calibration['geometry']['points']]
        bundle = existing or {'schema': 'prepared-circuit-v1', 'toolVersion': VERSION, 'identity': meta,
                              'calibration': calibration, 'geometryId': geometry_id(points), 'corners': None, 'sectors': None,
                              'verification': 'provisional', 'liveCompatibility': 'not-checked', 'complete': False, 'warnings': []}
        # Publish usable geometry before the optional offline annotations finish.
        store.publish(bundle)
        progress(stage='geometry', state='geometry-ready', complete=False)
        corners, sectors, warnings = importer(meta, calibration, store.root, progress)
        if corners is not None and bundle.get('corners') is None:
            bundle['corners'] = corners
        if sectors is not None and bundle.get('sectors') is None:
            bundle['sectors'] = sectors
        bundle['warnings'] = warnings
        bundle['complete'] = bool(bundle['corners'] and bundle['sectors'])
        store.publish(bundle)
        progress(stage='ready', state='ready', complete=bundle['complete'], warnings=warnings)
        return bundle
    except Exception as exc:
        safe = str(exc) if isinstance(exc, PreparationError) else 'Preparation failed. Check local authentication, data availability and geometry diagnostics. Existing assets retained.'
        progress(stage='failed', state='failed', error=safe)
        raise PreparationError(safe) from None
    finally:
        lock.unlink(missing_ok=True)


def batch(sessions, store, report=lambda **_: None, **options):
    results = []
    seen = set()
    for session in sessions:
        try:
            meta = identity(session)
            if meta['assetKey'] in seen:
                continue
            seen.add(meta['assetKey'])
            if meta['id']=='austin':
                results.append({'identity':meta,'state':'existing-local-reference','note':'Existing Austin public assets preserved; validate in dashboard.'})
                continue
            bundle = prepare(session, store, report, **options)
            results.append({'identity': meta, 'state': 'complete' if bundle['complete'] else 'incomplete'})
        except (PreparationError, KeyError, ValueError):
            results.append({'path': session.get('path'), 'state': 'failed', 'error': 'See per-circuit job.json or use a session with stable circuit metadata.'})
    atomic_json(store.root / 'batch.json', results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--event', help='Event/location substring; omitted with --batch for all available races')
    parser.add_argument('--session', default='Race')
    parser.add_argument('--batch', action='store_true')
    parser.add_argument('--retry-annotations', action='store_true', help='Compatibility option: incomplete annotations are retried by default; complete assets are skipped.')
    parser.add_argument('--windows', nargs='+', type=int, default=[5400, 6000, 3600])
    parser.add_argument('--store', default=str(DEFAULT_STORE))
    parser.add_argument('--login', action='store_true')
    args = parser.parse_args()
    if len(args.windows) > 5 or any(x < 0 or x > 14400 for x in args.windows):
        parser.error('Use 1–5 offsets between 0 and 14400 seconds')
    if not args.batch and not args.event:
        parser.error('Choose --event or --batch')
    try:
        if args.login:
            from livef1 import login
            login()
        from .archive import list_sessions
        sessions = [s for s in list_sessions(args.year) if s['session'] == args.session and
                    (not args.event or args.event.lower() in (s['event']+' '+str(s['location'])).lower())]
        if not sessions or (not args.batch and len(sessions) != 1):
            raise PreparationError('Select an unambiguous available session; no layout/season fallback was made')
        result = batch(sessions, AssetStore(args.store), report=lambda **v: print(json.dumps(v), flush=True), retry=True, windows=tuple(args.windows))
        print(json.dumps(result, indent=2))
        if any(r['state'] == 'failed' for r in result):
            raise SystemExit(1)
    except PreparationError as exc:
        parser.exit(1, str(exc)+'\n')
    except Exception:
        parser.exit(1, 'Preparation unavailable. Check local authentication/network; no account details printed.\n')


if __name__ == '__main__':
    main()
