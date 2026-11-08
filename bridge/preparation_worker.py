"""Dedicated FastF1 process. Same Austin math, independently saved stages."""
import argparse
import hashlib
import logging
from pathlib import Path
from .corner_import import fetch, align, read, write, ImportFailure, geometry_id
from .sector_import import collect_laps, add_boundaries
from .annotation_progress import atomic, Progress, FastF1Stages


def run(request):
    meta=request['identity'];calibration=read(request['calibration'])
    cache=Path(request['sourceCache']);cache.mkdir(parents=True,exist_ok=True)
    token=hashlib.sha256(meta['path'].encode()).hexdigest()
    fingerprint=geometry_id([[p['x'],p['y']] for p in calibration['geometry']['points']])
    checkpoints=Path(request.get('checkpoints',Path(request['output']).parent/'checkpoints'))
    checkpoints.mkdir(parents=True,exist_ok=True)
    reporter=Progress(request.get('diagnostics',checkpoints/'annotation-diagnostics.json'))
    corner_checkpoint=checkpoints/f'{token}-{fingerprint}-corners.json'
    sector_checkpoint=checkpoints/f'{token}-{fingerprint}-sectors.json'
    source_path=cache/f'{token}.json'
    warnings=[];corners=sectors=aligned=None

    def valid_annotation(value):
        return isinstance(value,dict) and value.get('schema')=='f1-circuit-annotations-v1' and value.get('circuitId')==meta['id'] and value.get('layoutVersion')==meta['layoutVersion'] and value.get('geometryId')==fingerprint

    def checkpoint(path):
        if not path.exists():return None
        try:
            value=read(path)
            return value if valid_annotation(value) else None
        except (OSError,ValueError):return None

    def output():atomic(request['output'],{'corners':corners,'sectors':sectors,'warnings':warnings})

    def check_source(source):
        if source.get('circuitId')!=meta['id'] or source.get('layoutVersion')!=meta['layoutVersion'] or str(source.get('circuitKey'))!=meta['circuitKey'] or source.get('year')!=meta['year'] or source.get('session')!=meta['session']:
            raise ImportFailure('Cached source circuit/layout/season/session mismatch')

    def metadata_ready(value):
        if str(value.get('circuitKey'))!=meta['circuitKey']:raise ImportFailure('FastF1 circuit identity mismatch')
        atomic(cache/f'{token}-metadata.json',value)
        reporter.event('corner-metadata-retrieval',metadataCorners=len(value['corners']))

    def source_ready(source):
        nonlocal corners,aligned
        source.update(circuitId=meta['id'],layoutVersion=meta['layoutVersion'])
        check_source(source)
        reporter.event('source-save')
        atomic(cache/f'{token}-corners-source.json',source)
        reporter.event('corner-registration')
        aligned=align(source,calibration,meta['id'],meta['layoutVersion'])
        if aligned['direction']!=1:raise ImportFailure('FastF1 driving direction disagrees with measured LiveF1 geometry')
        if corners is None:
            corners=dict(aligned);corners.pop('importSource',None)
            corners['sourceSession']={k:source[k] for k in ('year','event','session','provider')}
            atomic(corner_checkpoint,corners)
        reporter.event('corners-checkpoint',corners=len(corners['corners']))
        output()  # Parent can publish before multi-lap collection/calculation.

    handler=FastF1Stages(reporter.event)
    logger=logging.getLogger('fastf1');old_level=logger.level;logger.setLevel(logging.INFO);logger.addHandler(handler)
    try:
        corners=checkpoint(corner_checkpoint);sectors=checkpoint(sector_checkpoint)
        if corners or sectors:
            reporter.event('source-cache',checkpointHit=True);output()
        if corners and sectors:return
        reporter.event('source-cache')
        source=None
        if source_path.exists():
            try:source=read(source_path)
            except (OSError,ValueError):source_path.unlink(missing_ok=True)
        if source is None and (cache/f'{token}-corners-source.json').exists():
            source=read(cache/f'{token}-corners-source.json')
        if source is not None:
            check_source(source);reporter.event('source-cache',sourceCacheHit=True)
            source_ready(source)
        if source is None or not isinstance(source.get('boundaryLaps'),dict):
            source=fetch(meta['year'],meta['event'],meta['session'],request['cache'],
                         lap_collector=collect_laps,progress=reporter.event,
                         metadata_ready=metadata_ready,source_ready=source_ready)
            source.update(circuitId=meta['id'],layoutVersion=meta['layoutVersion']);check_source(source)
            reporter.event('source-save');atomic(source_path,source)
            # Injectable sources can return a full cache without invoking callbacks.
            if aligned is None:source_ready(source)
        if sectors is None:
            laps=source.get('boundaryLaps',{})
            if isinstance(laps,dict):reporter.event('multi-lap-collection',inspected=laps.get('inspected',0),accepted=len(laps.get('laps',[])),rejected=sum(laps.get('rejected',{}).values()))
            reporter.event('sector-calculation')
            sectors=add_boundaries(source,dict(aligned),calibration)
            sectors.pop('importSource',None);sectors['corners']=[]
            atomic(sector_checkpoint,sectors)
            reporter.event('sectors-checkpoint');output()
    except Exception as exc:
        reporter.failure(exc)
        warnings.append(f"FastF1 stage {reporter.value['phase']} failed ({type(exc).__name__}); inspect annotation-diagnostics.json. Geometry and completed annotations retained.")
    finally:
        logger.removeHandler(handler);logger.setLevel(old_level)
        # Source caches are disposable; checkpoints and public/local reviewed
        # assets are outside this prune operation and survive partial failures.
        files=sorted(cache.glob('*.json'),key=lambda p:p.stat().st_mtime)
        total=sum(p.stat().st_size for p in files)
        for path in files:
            if total<=128*1024*1024:break
            size=path.stat().st_size;path.unlink(missing_ok=True);total-=size
        output();reporter.finish(corners,sectors)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    run(read(parser.parse_args().request))


if __name__=='__main__':main()
