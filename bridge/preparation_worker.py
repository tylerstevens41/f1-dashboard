"""Dedicated FastF1-environment subprocess; never imports LiveF1/calibrate."""
import argparse
import hashlib
import json
from pathlib import Path
from .corner_import import fetch, align, read, write, ImportFailure
from .sector_import import collect_laps, add_boundaries


def run(request):
    meta = request['identity']
    calibration = read(request['calibration'])
    cache = Path(request['sourceCache'])
    cache.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(meta['path'].encode()).hexdigest()
    source_path = cache / f'{token}.json'
    warnings = []
    corners = sectors = None
    try:
        source = None
        if source_path.exists():
            try:
                source = read(source_path)
            except (OSError, ValueError):
                source_path.unlink(missing_ok=True)  # disposable interrupted cache, never reviewed assets
        if source is None:
            source = fetch(meta['year'], meta['event'], meta['session'], request['cache'], lap_collector=collect_laps)
            source.update(circuitId=meta['id'], layoutVersion=meta['layoutVersion'])
            if str(source['circuitKey']) != meta['circuitKey']:
                raise ImportFailure('FastF1 circuit identity mismatch')
            write(source_path, source)
        if str(source['circuitKey']) != meta['circuitKey'] or source['year'] != meta['year'] or source['session'] != meta['session']:
            raise ImportFailure('Cached source circuit/season/session mismatch')
        result = align(source, calibration, meta['id'], meta['layoutVersion'])
        if result['direction'] != 1:
            raise ImportFailure('FastF1 driving direction disagrees with measured LiveF1 geometry')
        corners = dict(result)
        corners.pop('importSource', None)  # keep raw multi-lap telemetry backend-only
        corners['sourceSession'] = {k: source[k] for k in ('year', 'event', 'session', 'provider')}
        try:
            sectors = add_boundaries(source, dict(result), calibration)
            sectors.pop('importSource', None)
            sectors['corners'] = []
        except ImportFailure as exc:
            warnings.append(str(exc))
    except ImportFailure as exc:
        warnings.append(str(exc))
    except Exception:
        warnings.append('FastF1 historical annotations unavailable. Geometry remains usable; check source access locally.')
    finally:
        # Source cache is bounded independently of FastF1's own 512 MiB cache.
        files = sorted(cache.glob('*.json'), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= 128*1024*1024:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
    write(request['output'], {'corners': corners, 'sectors': sectors, 'warnings': warnings})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    run(read(parser.parse_args().request))


if __name__ == '__main__':
    main()
