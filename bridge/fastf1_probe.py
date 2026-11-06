"""Short, isolated lap-loading probe. Does not read/write circuit geometry."""
import argparse
import subprocess
import sys
from .annotation_progress import Progress, FastF1Stages
from .fastf1_network import bounded_network


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--year',type=int,required=True)
    parser.add_argument('--event',required=True)
    parser.add_argument('--session',default='Race')
    parser.add_argument('--cache',default='data-cache/fastf1')
    parser.add_argument('--report',default='fastf1-probe.json')
    parser.add_argument('--seconds',type=int,default=45)
    parser.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not 1<=args.seconds<=120:parser.error('--seconds must be 1..120')
    if not args.child:
        try:
            result=subprocess.run([sys.executable,'-m','bridge.fastf1_probe',*sys.argv[1:],'--child'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=args.seconds)
            return result.returncode
        except subprocess.TimeoutExpired:
            import json
            from pathlib import Path
            from .annotation_progress import atomic
            path=Path(args.report)
            value=json.loads(path.read_text()) if path.exists() else {}
            value.update(state='timeout',timeoutSeconds=args.seconds)
            atomic(path,value)
            return 2
    reporter=Progress(args.report)
    import logging
    handler=FastF1Stages(reporter.event)
    logger=logging.getLogger('fastf1');logger.addHandler(handler);logger.setLevel(logging.INFO)
    try:
        import fastf1
        from pathlib import Path
        Path(args.cache).mkdir(parents=True,exist_ok=True)
        fastf1.Cache.enable_cache(args.cache)
        with bounded_network(reporter.event) as failures:
            reporter.event('fastf1-session-retrieval')
            session=fastf1.get_session(args.year,args.event,args.session)
            reporter.event('fastf1-laps-load')
            session.load(telemetry=False,weather=False,messages=False)
            if failures:raise failures[0]
            if session.laps.empty:raise ValueError('No laps loaded')
            reporter.event('multi-lap-collection',accepted=len(session.laps))
            reporter.finish(False,False)
            reporter.value['state']='probe-success'
            from .annotation_progress import atomic
            atomic(args.report,reporter.value)
        return 0
    except Exception as exc:
        reporter.failure(exc)
        return 1
    finally:logger.removeHandler(handler)


if __name__=='__main__':sys.exit(main())
