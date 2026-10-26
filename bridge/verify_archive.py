"""Safe local archive capability report, never prints credentials or payloads."""
import argparse
import importlib.metadata
import json
from .archive import ArchiveUnavailable, fetch_clip, list_sessions
from .protocol import TOPICS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year',type=int,default=2024)
    parser.add_argument('--meeting',default='Austin')
    parser.add_argument('--session',default='Race')
    parser.add_argument('--start',type=float,default=600)
    parser.add_argument('--duration',type=float,default=120)
    args = parser.parse_args()
    report = {'livef1Version':importlib.metadata.version('livef1'),'realArchiveVerified':False}
    try:
        choices = list_sessions(args.year)
        matches = [s for s in choices if args.meeting.lower() in (s['label']+' '+s['path']).lower() and args.session.lower() == s['label'].split(' · ')[-1].lower()]
        if len(matches) != 1:
            report['status'] = 'Session selection is missing or ambiguous; select the exact session in development controls.'
        else:
            clip = fetch_clip(matches[0]['path'],args.start,args.duration)
            report.update(realArchiveVerified=True,sessionPath=clip['sessionPath'],topics=clip['capabilities'],
                          events=len(clip['events']),clockBasis=clip.get('clockBasis'),
                          missingTopics=[t for t in TOPICS if clip['capabilities'].get(t) != 'available'])
    except ArchiveUnavailable as exc:
        report['status'] = str(exc) # controlled, sanitized archive error only
    except Exception:
        report['status'] = 'Archive verification failed. Check local network, authentication and library compatibility.'
    print(json.dumps(report,indent=2))
    return 0 if report['realArchiveVerified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
