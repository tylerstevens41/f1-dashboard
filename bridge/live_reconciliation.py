"""Strict reconciliation of an advisory with independently published LIVE identity.

No countdown activation, archive replay, manual-selection trust or GPS transforms.
"""
from datetime import datetime,timezone,timedelta
import json
import re
import unicodedata
from urllib.parse import urljoin

from .autonomous import name,utc_start,advisory_matches

TYPES={'Practice 1','Practice 2','Practice 3','Sprint Qualifying','Sprint','Qualifying','Race'}
PATH=re.compile(r'(20\d{2})/(20\d{2}-\d{2}-\d{2})_[A-Za-z0-9_-]+/(20\d{2}-\d{2}-\d{2})_([A-Za-z0-9_]+)/')


def provider_candidate(info,now):
    """Require explicit provider keys, path, type, local date and UTC start."""
    if not isinstance(info,dict):return None,'missing-session-info'
    path=info.get('Path');match=PATH.fullmatch(path) if isinstance(path,str) else None
    if not match:return None,'invalid-provider-path'
    year,meeting_day,session_day,path_type=match.groups();year=int(year)
    if not isinstance(info.get('Name'),str):return None,'missing-session-type'
    kind=name(info.get('Name'))
    if kind not in TYPES or name(path_type.replace('_',' '))!=kind:return None,'session-type-conflict'
    family={'Race':{'Race'},'Sprint':{'Race','Sprint'},'Qualifying':{'Qualifying'},'Sprint Qualifying':{'Qualifying','Sprint Qualifying','Sprint Shootout'}}.get(kind,{'Practice'})
    if info.get('Type') is not None and (not isinstance(info['Type'],str) or info['Type'] not in family):return None,'session-type-conflict'
    meeting=info.get('Meeting');circuit=meeting.get('Circuit') if isinstance(meeting,dict) else None
    if not isinstance(circuit,dict):return None,'missing-circuit-identity'
    # Provider keys are concrete numeric IDs, not descriptive labels or placeholders.
    for value in (info.get('Key'),meeting.get('Key'),circuit.get('Key')):
        if isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value).isdigit() or len(str(value))>20 or int(value)<=0:return None,'missing-provider-keys'
    if not all(isinstance(v,str) and v.strip() for v in (circuit.get('ShortName'),meeting.get('Name'))):return None,'missing-provider-names'
    candidate={'path':path,'year':year,'session':kind,'start':info.get('StartDate'),
               'gmtOffset':info.get('GmtOffset'),'providerStartDate':info.get('StartDate'),
               'event':meeting['Name'],'location':meeting.get('Location',circuit['ShortName']),
               'circuit':dict(circuit),'meetingKey':meeting['Key'],'sessionKey':info['Key']}
    start=utc_start(candidate)
    if start is None:return None,'unknown-provider-timezone-or-start'
    if year!=datetime.fromtimestamp(now,timezone.utc).year or not now-43200<=start<=now+900:return None,'provider-session-outside-current-window'
    try:
        date=datetime.fromisoformat(str(info['StartDate']).replace('Z','+00:00'))
        if date.tzinfo is not None and info.get('GmtOffset'):
            offset=re.fullmatch(r'([+-]?)(\d{1,2}):(\d{2})(?::(\d{2}))?',str(info['GmtOffset']))
            if not offset:return None,'invalid-provider-offset'
            sign,hour,minute,second=offset.groups()
            hour,minute,second=int(hour),int(minute),int(second or 0)
            if hour>14 or minute>59 or second>59:return None,'invalid-provider-offset'
            delta=timedelta(hours=hour,minutes=minute,seconds=second)
            date=date.astimezone(timezone(-delta if sign=='-' else delta))
        day=datetime.fromisoformat(session_day)
        meeting_date=datetime.fromisoformat(meeting_day)
        if date.date()!=day.date() or day.year!=year or meeting_date.year!=year or abs((day-meeting_date).days)>7:return None,'provider-path-date-conflict'
    except (ValueError,TypeError):return None,'provider-path-date-conflict'
    return candidate,None


def reconcile(now,advisory,observation,confirmation=None,catalog=()):
    """Return a candidate only after advisory + feed + independent metadata agree."""
    def reject(reason):return None,{'status':'blocked','reason':reason}
    def verified(current,source):
        result={**current,'advisoryId':advisory.get('advisoryId'),'identitySource':'live-feed-plus-'+source}
        return result,{'status':'verified-current-provider-session','reason':'advisory, current feed and independent provider identity agree; fresh telemetry',
                       'source':source,'path':current['path'],'sessionKey':current['sessionKey'],'circuitKey':str(current['circuit']['Key'])}
    if observation.get('dataMode')!='LIVE':return reject('not-live-data')
    if not observation.get('sourceRunning') or observation.get('upstream')!='connected':return reject('live-source-not-connected')
    if observation.get('identityConfirmed') is not True:return reject('feed-identity-not-confirmed')
    if observation.get('status') not in ('Started','Resumed'):return reject('session-not-started')
    if not (observation.get('freshGps') or observation.get('freshDelta')):return reject('live-telemetry-not-fresh')
    current,error=provider_candidate(observation.get('session'),now)
    if error:return reject(error)
    if not isinstance(advisory,dict) or advisory.get('path') or advisory.get('year')!=current['year'] or not advisory_matches(current,advisory):return reject('advisory-provider-conflict')
    norm=lambda value:re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower())
    if norm(advisory.get('event'))!=norm(current['event']):return reject('advisory-event-conflict')
    expected=observation.get('expectedPath')
    if expected is not None and expected!=current['path']:return reject('expected-feed-path-conflict')
    advisory_key=(advisory.get('circuit') or {}).get('Key')
    if advisory_key is not None and str(advisory_key)!=str(current['circuit']['Key']):return reject('advisory-circuit-conflict')
    if advisory.get('meetingKey') is not None and str(advisory['meetingKey'])!=str(current['meetingKey']):return reject('advisory-meeting-conflict')
    for row in catalog:
        if not isinstance(row,dict) or not row.get('path'):continue
        if row['path']==current['path']:
            if row.get('year') is not None and row['year']!=current['year']:return reject('catalog-year-conflict')
            if row.get('session') and name(row['session'])!=current['session']:return reject('catalog-type-conflict')
            if row.get('event') and norm(row['event'])!=norm(current['event']):return reject('catalog-event-conflict')
            if row.get('sessionKey') is not None and str(row['sessionKey'])!=str(current['sessionKey']):return reject('catalog-session-key-conflict')
            key=(row.get('circuit') or {}).get('Key')
            if key is not None and str(key)!=str(current['circuit']['Key']):return reject('catalog-circuit-conflict')
            if row.get('meetingKey') is not None and str(row['meetingKey'])!=str(current['meetingKey']):return reject('catalog-meeting-conflict')
            stamp=utc_start(row)
            if stamp is not None and abs(stamp-utc_start(current))>1:return reject('catalog-start-conflict')
        elif row.get('year')==current['year'] and advisory_matches(row,advisory):
            return reject('ambiguous-published-session')
    if confirmation is None:
        # The year index can corroborate an untimed entry that combine_schedule
        # dropped: retain its literal local StartDate rather than guessing GMT.
        # Require every independent index identity field, not a user selection.
        indexed=any(isinstance(row,dict) and row.get('path')==current['path'] and
                    row.get('year')==current['year'] and name(row.get('session'))==current['session'] and
                    str((row.get('circuit') or {}).get('Key'))==str(current['circuit']['Key']) and
                    str(row.get('meetingKey'))==str(current['meetingKey']) and
                    str(row.get('sessionKey'))==str(current['sessionKey']) and
                    isinstance(row.get('start'),str) and row['start']==current['start'] for row in catalog)
        if indexed:return verified(current,'year-index')
        return None,{'status':'provider-confirmation-required','reason':'feed checks passed; independent session metadata required','path':current['path']}
    if not isinstance(confirmation,dict) or confirmation.get('path')!=current['path']:return reject('provider-confirmation-path-conflict')
    document=confirmation.get('sessionInfo')
    if not isinstance(document,dict):return reject('missing-independent-provider-identity')
    if document.get('Path') not in (None,current['path']):return reject('provider-document-path-conflict')
    # The request directory independently anchors the document if its payload
    # omits Path. Never fill missing keys/type/start/circuit from the live feed.
    published,error=provider_candidate({**document,'Path':current['path']},now)
    if error:return reject('provider-document-'+error)
    for key in ('year','session','sessionKey','meetingKey'):
        if str(published[key])!=str(current[key]):return reject('provider-document-'+key+'-conflict')
    if str(published['circuit']['Key'])!=str(current['circuit']['Key']):return reject('provider-document-circuit-conflict')
    if abs(utc_start(published)-utc_start(current))>1:return reject('provider-document-start-conflict')
    def offset_seconds(value):
        match=re.fullmatch(r'([+-]?)(\d{1,2}):(\d{2})(?::(\d{2}))?',str(value))
        if not match:return None
        sign,h,m,sec=match.groups()
        return (-1 if sign=='-' else 1)*(int(h)*3600+int(m)*60+int(sec or 0))
    if current['gmtOffset'] is not None and published['gmtOffset'] is not None and offset_seconds(current['gmtOffset'])!=offset_seconds(published['gmtOffset']):return reject('provider-document-offset-conflict')
    if published['event']!=current['event'] or published['circuit']['ShortName']!=current['circuit']['ShortName']:return reject('provider-document-names-conflict')
    return verified(current,'current-session-keyframe' if confirmation.get('source')=='current-session-keyframe' else 'independent-session-metadata')


def archived_session_info(path):
    """Bounded, authenticated per-session metadata fetch; no telemetry download.

    Resolve the real SessionInfo stream from its Index, not a guessed filename.
    This is called off the event loop. Standard archive timeout/auth handling apply.
    """
    from .archive import small_json,lines,split_stream_record,ArchiveUnavailable
    from .protocol import merge
    if not isinstance(path,str) or not PATH.fullmatch(path):raise ValueError('Invalid session directory')
    feeds=small_json(path+'Index.json').get('Feeds',{})
    feed=feeds.get('SessionInfo',{}) if isinstance(feeds,dict) else {}
    stream=feed.get('StreamPath') if isinstance(feed,dict) else None
    target=urljoin(path,stream) if isinstance(stream,str) else ''
    if not stream:raise ArchiveUnavailable('SessionInfo metadata stream unavailable',code='topic-unpublished')
    if not target.startswith(path) or not target.endswith('.jsonStream'):raise ArchiveUnavailable('Invalid metadata stream path',code='invalid-stream-path')
    value={};budget=[0]
    for index,line in enumerate(lines(target,budget,limit=1024*1024)):
        if index>=128:raise ArchiveUnavailable('SessionInfo record limit',code='record-limit')
        _,text=split_stream_record(line);payload=json.loads(text)
        if not isinstance(payload,dict):raise ValueError('Invalid SessionInfo metadata')
        value=merge(value,payload)
    return {'path':path,'sessionInfo':value}


def published_session_info(path):
    """Try archive publication, then the distinct official current keyframe.

    The root endpoint is fixed, not built from a guessed session path. Read it
    with the same authentication/access policy. It must supply its OWN Path;
    the caller's expected path is never inserted into a current-session payload.
    Strict reconciliation still rejects stale/different/missing identities.
    """
    from .archive import ArchiveUnavailable,small_json
    try:return archived_session_info(path)
    except ArchiveUnavailable as exc:
        if exc.code not in ('archive-access-denied','authentication-required','topic-unpublished'):raise
    value=small_json('SessionInfo.json')
    if not isinstance(value,dict) or not isinstance(value.get('Path'),str) or not PATH.fullmatch(value['Path']):
        raise ValueError('Current provider keyframe has no explicit valid session path')
    return {'path':value['Path'],'sessionInfo':value,'source':'current-session-keyframe'}
