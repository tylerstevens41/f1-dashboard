"""Sanitized local metadata/auth probe; no LIVE subscription or circuit writes."""
import argparse
import json
import logging
from .archive import list_sessions,request_diagnostics
from .live_reconciliation import published_session_info
from .diagnostics import safe_exception


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--year',required=True,type=int);p.add_argument('--event',required=True)
    p.add_argument('--path',required=True,help='Exact provider path from feedEvidence, never guessed')
    p.add_argument('--login',action='store_true');args=p.parse_args()
    logging.getLogger('livef1').disabled=True
    result={'schema':'provider-metadata-probe-v1','year':args.year,'event':args.event}
    if args.login:
        try:
            from livef1 import login
            login()
        except Exception as exc:
            print(json.dumps({'error':safe_exception(exc,'archive')}));return 1
    index={};identity={}
    try:
        with request_diagnostics(index):sessions=list_sessions(args.year)
        result['catalog']={'pathEntries':sum(s['path']==args.path for s in sessions),
                           'eventSessions':[{'session':s['session'],'path':s['path']} for s in sessions if args.event.casefold() in str(s.get('event','')).casefold()]}
    except Exception as exc:result['catalogError']=safe_exception(exc,'archive')
    try:
        with request_diagnostics(identity):document=published_session_info(args.path)
        info=document['sessionInfo']
        result['metadata']={'path':document['path'],'session':info.get('Name'),'sessionKey':info.get('Key'),
                            'meetingKey':info.get('Meeting',{}).get('Key'),'circuit':info.get('Meeting',{}).get('Circuit'),
                            'start':info.get('StartDate'),'gmtOffset':info.get('GmtOffset')}
    except Exception as exc:result['metadataError']=safe_exception(exc,'archive')
    result.update(indexRequests=index,metadataRequests=identity)
    print(json.dumps(result,indent=2))
    return 1 if 'metadataError' in result else 0


if __name__=='__main__':raise SystemExit(main())
