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
        from .annotation_progress import replace_file
        replace_file(temporary, path)
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
    if bundle.get('complete') and not annotations_complete(bundle):
        raise PreparationError('Complete asset requires imported corners and successful multi-lap timing boundaries')
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


def annotations_complete(bundle):
    """Completion is successful shared import/calculation, never verification."""
    corners=bundle.get('corners') or {}
    sectors=bundle.get('sectors') or {}
    valid_laps=(sectors.get('boundaryDiagnostics') or {}).get('validLaps',0)
    return bool(corners.get('corners') and corners.get('alignment') and
                isinstance(valid_laps,int) and not isinstance(valid_laps,bool) and valid_laps>=5 and
                all(isinstance(sectors.get(key),dict) and sectors[key].get('calculated') is True
                    for key in ('startFinish','sector1End','sector2End')))


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
        previous = self.directory(meta['assetKey']) / 'job.json'
        retained = {}
        if previous.exists():
            try:
                old=read_json(previous)
                retained={k:old[k] for k in ('windowDiagnostics','annotationDiagnostics') if k in old}
            except (ValueError,OSError):
                pass
        record = {'identity': meta, 'updatedAt': time.time(), **retained, **value}
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
    from collections import Counter
    import numpy as np
    from .archive import fetch_clip
    from .calibrate import collect_clip, clean_laps, build, read_json as read_samples, write_json
    from .diagnostics import safe_exception
    from .protocol import TOPICS
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    attempts = []
    pending=list(windows)
    discovered={}
    usable_scan_attempted=False
    diagnostic_file = cache.parent / meta['assetKey'] / 'geometry-diagnostics.json'

    def publish():
        payload = {'schema':'circuit-geometry-diagnostics-v1','circuitKey':meta['circuitKey'],
                   'year':meta['year'],'layoutVersion':meta['layoutVersion'],'windows':attempts}
        atomic_json(diagnostic_file, payload)
        report(stage='collecting', state='preparing', windowStart=attempts[-1]['offset'], windowDiagnostics=attempts)

    for offset in pending:
        diagnostic = {'offset':offset,'durationSeconds':480,'stage':'cache','status':'running',
                      'sampleCacheHit':False,'archiveRetrieved':None,'eventCount':None,
                      'positionMessages':None,'decodedPositionRecords':None,'driversRepresented':None,
                      'candidateLaps':None,'acceptedCompleteLaps':None,'calibrationAttempted':False}
        diagnostic['windowSource']=discovered.get(offset,'requested')
        attempts.append(diagnostic)
        try:
            publish()
            token = hashlib.sha256(f"{meta['path']}:{offset}:480:extraction-v2".encode()).hexdigest()
            file = cache / f'{token}.json.gz'
            diagnostic['sampleCacheEntry']=file.name
            if file.exists():
                data = read_samples(file)
                diagnostic.update(data.get('collectionDiagnostics',{}))
                diagnostic['sampleCacheHit'] = True
                diagnostic['windowSource']=discovered.get(offset,'requested')
            else:
                diagnostic['stage']='archive'
                retrieval={}
                try:
                    clip = fetch_clip(meta['path'], offset, 480, topics=('SessionInfo','TimingData','Position.z'),diagnostics=retrieval)
                finally:
                    diagnostic.update(retrieval)
                diagnostic['archiveRetrieved']=True
                if not isinstance(clip,dict) or not isinstance(clip.get('events'),list):
                    raise PreparationError('Unexpected archive clip schema; inspect archive/extraction stage')
                diagnostic['eventCount']=len(clip['events'])
                diagnostic['topicEvents']={t:n for t,n in Counter(e.get('topic') for e in clip['events'] if isinstance(e,dict)).items() if t in TOPICS}
                allowed={'available','no-events-in-window','missing','missing-stream','parse-error','static-metadata-only'}
                diagnostic['capabilities']={t:v for t,v in clip.get('capabilities',{}).items() if t in TOPICS and v in allowed}
                diagnostic['clockBasis']=clip.get('clockBasis') if clip.get('clockBasis') in ('gps-utc','relative','receipt-utc') else 'unknown'
                diagnostic['stage']='extract'
                extraction={}
                try:
                    samples=collect_clip(clip, diagnostics=extraction)
                finally:
                    diagnostic.update(extraction)
                data = {'schema':'livef1-calibration-samples-v1','source':'LiveF1','circuitId':meta['id'],
                        'sessionPath':meta['path'],'sessionPaths':[meta['path']],'samples':samples, 'synthetic':bool(clip.get('synthetic',False))}
                diagnostic['stage']='identity'
                info = clip['initial'].get('SessionInfo', {})
                for event in clip['events']:
                    if event['topic'] == 'SessionInfo':
                        from .protocol import merge
                        info = merge(info, event['payload'])
                if str(info.get('Meeting', {}).get('Circuit', {}).get('Key')) != meta['circuitKey']:
                    raise PreparationError('Archive GPS circuit identity mismatch')
                data['collectionDiagnostics']=dict(diagnostic)
                diagnostic['stage']='cache'
                write_json(file, data)
            if data.get('schema')!='livef1-calibration-samples-v1' or data.get('source')!='LiveF1' or not isinstance(data.get('samples'),list):
                raise PreparationError('Unexpected cached GPS sample schema')
            if data.get('circuitId') != meta['id'] or data.get('sessionPath') != meta['path']:
                raise PreparationError('Cached GPS source identity mismatch')
            diagnostic['sampleCount']=len(data['samples'])
            diagnostic['driversRepresented']=len({p.get('driver') for p in data['samples'] if isinstance(p,dict) and p.get('driver') is not None})
            skews=[p['time']-p['frameTime'] for p in data['samples'] if isinstance(p,dict) and all(isinstance(p.get(k),(int,float)) and np.isfinite(p[k]) for k in ('time','frameTime'))]
            diagnostic['sampleClockSkewMs']={'median':float(np.median(skews)),'absoluteP95':float(np.percentile(np.abs(skews),95))} if skews else None
            diagnostic['stage']='clean'
            cleaning={}
            try:
                laps, rejected = clean_laps(data, diagnostics=cleaning)
            finally:
                diagnostic.update(cleaning)
            if not data['samples']:
                diagnostic.update(status='rejected',reason='no-position-samples')
                continue
            if len(laps) < 3:
                reason='no-valid-position-samples' if rejected['invalid']==len(data['samples']) else 'insufficient-complete-laps'
                diagnostic.update(status='rejected',reason=reason,requiredCompleteLaps=3)
                # All-zero/missing-lap windows are not usable race footage. Scan
                # once for measured timing + moving GPS, not arbitrary offsets.
                zero_only=diagnostic.get('invalidSampleReasons',{}).get('zeroCoordinates')==len(data['samples'])
                no_laps=diagnostic.get('lapNumberAvailability',{}).get('usable')==0
                if (zero_only or no_laps) and not usable_scan_attempted and len(discovered)<2:
                    usable_scan_attempted=True
                    from .window_scan import find_usable_window
                    scan={};diagnostic['usableWindowScan']=scan
                    publish()
                    try:
                        candidate=find_usable_window(meta['path'],offset+480,scan,on_progress=publish)
                        if candidate not in pending:
                            pending.append(candidate);discovered[candidate]='measured-lap-timing-and-moving-gps'
                            diagnostic['discoveredWindow']={'offset':candidate,'reason':discovered[candidate],'source':'bounded source scan; original source timestamps preserved'}
                    except Exception as exc:
                        scan['error']=safe_exception(exc,'archive')
                continue
            report(stage='geometry', state='preparing', windowStart=offset, windowDiagnostics=attempts)
            diagnostic['stage']='build'
            areas = [float(np.sum(lap['points'][:,0]*np.roll(lap['points'][:,1],-1)-np.roll(lap['points'][:,0],-1)*lap['points'][:,1])) for lap in laps]
            if any(abs(area)<1e-6 for area in areas) or len({bool(area>0) for area in areas}) != 1:
                from .trajectory_order import direction_consensus
                diagnostic['orderedDirection']=direction_consensus(laps)
                if not diagnostic['orderedDirection']['passed']:
                    diagnostic.update(status='rejected',reason='inconsistent-driving-direction-or-degenerate-loop')
                    continue
            diagnostic['calibrationAttempted']=True
            result = build(data, layout=meta['layoutVersion'])
            checks=result['validation']
            diagnostic['calibration']={k:checks.get(k) for k in ('automaticChecksPassed','heldOut','thresholdFractionOfDiagonal','lapCount','driverCount')}
            if not checks['automaticChecksPassed']:
                diagnostic.update(status='rejected',reason='held-out-geometry-error')
                continue
            xy = np.array([[p['x'], p['y']] for p in result['geometry']['points']])
            ratio=float(np.max(np.linalg.norm(np.diff(xy, axis=0), axis=1))/np.linalg.norm(np.ptp(xy, axis=0)))
            diagnostic['maximumSpatialStepFractionOfExtent']=ratio
            if not np.isfinite(ratio) or ratio>.04:
                diagnostic.update(status='rejected',reason='incomplete-spatial-coverage')
                continue
            diagnostic.update(stage='geometry',status='accepted')
            result.pop('debug', None)
            result['provenance']['preparationWindowSeconds'] = offset
            result['validation']['preparationDiagnostics']={'windows':attempts}
            return result
        except Exception as exc:
            diagnostic['status']='error'
            if diagnostic['stage']=='archive' and diagnostic['archiveRetrieved'] is not True:diagnostic['archiveRetrieved']=False
            diagnostic['error']=safe_exception(exc,diagnostic['stage'])
            # Only no-events responses with observed GPS coverage can suggest a
            # different source-clock window. Never rebase or shift timestamps.
            if diagnostic['stage']=='archive' and getattr(exc,'code',None)=='no-events' and len(discovered)<2:
                from .archive import MAX_START_SECONDS
                first=diagnostic.get('archiveFirstOffsetSeconds',{}).get('Position.z')
                after=diagnostic.get('archiveFirstAfterWindowSeconds',{}).get('Position.z')
                last=diagnostic.get('archiveLastOffsetSeconds',{}).get('Position.z')
                candidate=None
                reason=None
                if isinstance(after,(int,float)) and np.isfinite(after):
                    candidate=int(np.floor(after));reason='observed-gps-after-requested-window'
                elif all(isinstance(v,(int,float)) and np.isfinite(v) for v in (first,last)) and last-first>=480:
                    candidate=max(int(np.floor(first)),int(np.floor(last-480)));reason='observed-gps-ends-before-requested-window'
                if candidate is not None and 0<=candidate<=MAX_START_SECONDS and candidate not in pending:
                    pending.append(candidate);discovered[candidate]=reason
                    diagnostic['discoveredWindow']={'offset':candidate,'reason':reason,'source':'measured Position.z elapsed coverage; timestamps unchanged'}

            # These exact coordinator-generated messages are safe; arbitrary
            # ValueError/upstream messages are deliberately never forwarded.
            if isinstance(exc,PreparationError) and str(exc) in (
                'Unexpected archive clip schema; inspect archive/extraction stage',
                'Archive GPS circuit identity mismatch','Cached GPS source identity mismatch',
                'Unexpected cached GPS sample schema'):
                diagnostic['error']['detail']=str(exc)
        finally:
            publish()
            prune_cache(cache)
    raise PreparationError(f'No reliable geometry in {len(attempts)} bounded windows. See geometry-diagnostics.json and per-window stage/error/rejection details; no quality thresholds were relaxed.')


def fast_python():
    configured = os.environ.get('F1_FASTF1_PYTHON')
    return Path(configured) if configured else ROOT / '.venv-fastf1' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def import_annotations(meta, calibration, root, report, runner=None, process_factory=None,
                       timeout=600, poll_interval=.5, clock=time.monotonic, sleep=time.sleep):
    executable=fast_python()
    if not executable.is_file():
        return None,None,['FastF1 environment missing. Create .venv-fastf1 from bridge/requirements-corners.txt or set F1_FASTF1_PYTHON.']
    from .corner_import import geometry_id
    directory=Path(root)/meta['assetKey'];directory.mkdir(parents=True,exist_ok=True)
    diagnostics=directory/'annotation-diagnostics.json'
    worker_progress=directory/'annotation-worker-progress.json'
    checkpoints=directory/'annotations'
    token=hashlib.sha256(meta['path'].encode()).hexdigest()
    fingerprint=geometry_id([[p['x'],p['y']] for p in calibration['geometry']['points']])
    partial={'corners':None,'sectors':None,'warnings':[]};last_result=None;last_diagnostic=None
    extra=[]
    with tempfile.TemporaryDirectory(prefix='f1-import-',dir=root) as temp:
        temp=Path(temp);atomic_json(temp/'calibration.json',calibration)
        request={'identity':meta,'calibration':str(temp/'calibration.json'),'output':str(temp/'result.json'),
                 'cache':str(Path(root)/'fastf1-cache'),'sourceCache':str(Path(root)/'annotation-sources'),
                 'diagnostics':str(worker_progress),'checkpoints':str(checkpoints)}
        atomic_json(temp/'request.json',request)
        if diagnostics.exists():
            try:atomic_json(directory/'annotation-diagnostics.previous.json',read_json(diagnostics))
            except (OSError,ValueError):pass
        from .annotation_progress import Progress
        Progress(worker_progress)  # Worker owns this file; parent owns diagnostic heartbeats.
        atomic_json(diagnostics,read_json(worker_progress))

        def inspect_progress():
            nonlocal last_result,last_diagnostic,partial
            current=None
            if worker_progress.exists():
                try:current=read_json(worker_progress)
                except (OSError,ValueError):pass  # atomic replacement/restart race
            if current:
                now=time.time()
                if current.get('state')=='running':current['elapsedSeconds']=max(0,int((now-current.get('startedAt',now))/5)*5)
                current['phaseElapsedSeconds']=max(0,int((now-current.get('phaseStartedAt',now))/5)*5)
                marker=json.dumps(current,sort_keys=True)
                if marker!=last_diagnostic:
                    last_diagnostic=marker
                    atomic_json(diagnostics,current)
                    report(stage='annotations',state='preparing',annotationDiagnostics=current)
            value=None
            if (temp/'result.json').exists():
                try:value=read_json(temp/'result.json')
                except (OSError,ValueError):pass
            if value is None:
                value={'corners':None,'sectors':None,'warnings':[]}
                for key in ('corners','sectors'):
                    file=checkpoints/f'{token}-{fingerprint}-{key}.json'
                    if file.exists():
                        try:value[key]=read_json(file)
                        except (OSError,ValueError):pass
            marker=json.dumps(value,sort_keys=True)
            if marker!=last_result:
                last_result=marker;partial=value
                if value.get('corners') or value.get('sectors'):
                    report(stage='annotation-checkpoint',state='preparing',annotationPartial=value)

        report(stage='annotations',state='preparing')
        args=[str(executable),'-m','bridge.preparation_worker','--request',str(temp/'request.json')]
        process=None
        try:
            if runner is not None:  # Injectable synchronous runner for existing integrations/tests.
                result=runner(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=timeout,check=False)
                inspect_progress()
                if result.returncode!=0:extra.append('FastF1 worker exited unsuccessfully; inspect annotation-diagnostics.json.')
            else:
                process=(process_factory or subprocess.Popen)(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                started=clock()
                while process.poll() is None:
                    inspect_progress()
                    if clock()-started>=timeout:raise subprocess.TimeoutExpired(args,timeout)
                    sleep(poll_interval)
                inspect_progress()
                if process.returncode!=0:extra.append('FastF1 worker exited unsuccessfully; inspect annotation-diagnostics.json.')
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill();process.wait()
            inspect_progress()
            record=read_json(diagnostics) if diagnostics.exists() else {'phase':'worker-startup'}
            now=time.time()
            record.update(state='timeout',timedOut=True,timeoutSeconds=timeout,updatedAt=now,
                          elapsedSeconds=round(max(0,now-record.get('startedAt',now)),3),
                          phaseElapsedSeconds=round(max(0,now-record.get('phaseStartedAt',now)),3))
            atomic_json(diagnostics,record)
            report(stage='annotations',state='preparing',annotationDiagnostics=record)
            extra.append(f"FastF1 annotation preparation exceeded {timeout} seconds during {record.get('phase','unknown')}; geometry and completed annotations retained. Inspect annotation-diagnostics.json.")
        except (OSError,ValueError):
            inspect_progress()
            extra.append('FastF1 annotation process/checkpoint failed; geometry and completed annotations retained. Inspect annotation-diagnostics.json.')
        finally:
            if process is not None and process.poll() is None:
                process.kill();process.wait()
        return partial.get('corners'),partial.get('sectors'),partial.get('warnings',[])+extra


def prepare(session, store=None, report=lambda **_: None, retry=True, windows=(5400, 6000, 3600), collector=collect_geometry, importer=import_annotations, annotations_only=False):
    from .corner_import import geometry_id
    store = store or AssetStore()
    meta = identity(session)
    def progress(**value):
        partial=value.pop('annotationPartial',None)
        if partial:
            candidate=copy.deepcopy(bundle)
            for key in ('corners','sectors'):
                if candidate.get(key) is None and partial.get(key) is not None:candidate[key]=partial[key]
            candidate['complete']=annotations_complete(candidate)
            store.publish(candidate)  # validate before replacing the pointer
            bundle.update(candidate)
            value.update(cornersReady=bool(bundle.get('corners')),sectorsReady=bool(bundle.get('sectors')),complete=bundle['complete'])
        record = store.progress(meta, **value)
        report(**record)
    existing = store.get(meta)
    if annotations_only and existing is None:raise PreparationError('Annotations-only requires existing accepted geometry; no GPS collection was attempted')
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
        progress(stage='geometry', state='geometry-ready', complete=False,geometryReused=bool(existing))
        corners, sectors, warnings = importer(meta, calibration, store.root, progress)
        if corners is not None and bundle.get('corners') is None:
            bundle['corners'] = corners
        if sectors is not None and bundle.get('sectors') is None:
            bundle['sectors'] = sectors
        bundle['warnings'] = warnings
        bundle['complete'] = annotations_complete(bundle)
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


def cli_progress(**value):
    # Detailed history lives in the diagnostic file. Do not repeat the entire
    # geometry report and 200-event history on every annotation heartbeat.
    if value.get('annotationDiagnostics'):
        diagnostic=value['annotationDiagnostics']
        value={k:v for k,v in value.items() if k!='windowDiagnostics'}
        value['annotationDiagnostics']={k:diagnostic[k] for k in (
            'phase','state','startedAt','updatedAt','elapsedSeconds','phaseElapsedSeconds',
            'inspected','accepted','rejected','metadataCorners','corners','failedPhase','error','timedOut') if k in diagnostic}
    print(json.dumps(value),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--event', help='Event/location substring; omitted with --batch for all available races')
    parser.add_argument('--session', default='Race')
    parser.add_argument('--batch', action='store_true')
    parser.add_argument('--annotations-only',action='store_true',help='Require existing geometry; never collect or rebuild GPS geometry.')
    parser.add_argument('--retry-annotations', action='store_true', help='Compatibility option: incomplete annotations are retried by default; complete assets are skipped.')
    parser.add_argument('--windows', nargs='+', type=int, default=[5400, 6000, 3600])
    parser.add_argument('--store', default=str(DEFAULT_STORE))
    parser.add_argument('--login', action='store_true')
    args = parser.parse_args()
    if len(args.windows) > 5 or any(x < 0 or x > 604800 for x in args.windows):
        parser.error('Use 1–5 source offsets between 0 and 604800 seconds')
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
        result = batch(sessions, AssetStore(args.store), report=cli_progress, retry=True, windows=tuple(args.windows),annotations_only=args.annotations_only)
        print(json.dumps(result, indent=2))
        if any(r['state'] == 'failed' for r in result):
            raise SystemExit(1)
    except PreparationError as exc:
        parser.exit(1, str(exc)+'\n')
    except Exception:
        parser.exit(1, 'Preparation unavailable. Check local authentication/network; no account details printed.\n')


if __name__ == '__main__':
    main()
