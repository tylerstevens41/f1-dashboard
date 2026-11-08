"""Control plane only. No GPS fabrication, rendering or alternative live transport."""
import argparse
from datetime import datetime,timezone,timedelta
import json
import re
import unicodedata

STATES={'DASHBOARD','SESSION_APPROACHING','WAITING_FOR_SESSION','CONNECTING','LIVE','LIVE_STALE','SESSION_SUSPENDED','SESSION_COMPLETED','RECOVERING'}
LIVE_STATES={'LIVE','LIVE_STALE','SESSION_SUSPENDED','RECOVERING','SESSION_COMPLETED'}
NAMES={'Sprint Shootout':'Sprint Qualifying','Sprint Qualification':'Sprint Qualifying','Grand Prix':'Race'}


def name(value):return NAMES.get(value,value)


def utc_start(session):
    value=session.get('start')
    if not isinstance(value,str):return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:
            offset=session.get('gmtOffset')
            match=re.fullmatch(r'([+-]?)(\d{1,2}):(\d{2})(?::(\d{2}))?',offset) if isinstance(offset,str) else None
            if not match:return None
            sign,hour,minute,second=match.groups();hour=int(hour);minute=int(minute);second=int(second or 0)
            if hour>14 or minute>59 or second>59:return None
            duration=timedelta(hours=hour,minutes=minute,seconds=second)
            parsed=parsed.replace(tzinfo=timezone(-duration if sign=='-' else duration))
        return parsed.timestamp()
    except (TypeError,ValueError):return None


def identity_matches(selected,info):
    if not selected or not info:return False
    if info.get('Path'):
        if info['Path']!=selected.get('path'):return False
        actual_key=info.get('Meeting',{}).get('Circuit',{}).get('Key')
        expected_key=selected.get('circuit',{}).get('Key')
        return (actual_key is None or expected_key is None or str(actual_key)==str(expected_key)) and (not info.get('Name') or name(info['Name'])==name(selected.get('session')))
    key=info.get('Meeting',{}).get('Circuit',{}).get('Key')
    return (str(key)==str(selected.get('circuit',{}).get('Key')) and
            name(info.get('Name'))==name(selected.get('session')) and
            str(info.get('StartDate',''))[:10]==str(selected.get('providerStartDate',selected.get('start','')))[:10])


class SessionController:
    def __init__(self,saved=None):
        saved=saved or {}
        self.mode=saved.get('mode','AUTO') if saved.get('mode') in ('AUTO','MANUAL') else 'AUTO'
        self.state='DASHBOARD';self.selected=None;self.upcoming=None
        self.completed=list(saved.get('completed',[]))[-100:]
        self.history=list(saved.get('history',[]))[-100:];self.reason='startup; live identity requires revalidation'
        self.changed_at=0;self.last_live=None;self.completion_since=None;self.completion_observations=0
        self.presenting=False;self.last_attempt_at=0;self.retry_at=0;self.attempts=0;self.total_attempts=0;self.circuit='not-resolved'

    def set_mode(self,mode,now):
        if mode not in ('AUTO','MANUAL'):raise ValueError('Invalid controller mode')
        self.mode=mode;self.selected=None;self.last_live=None;self.presenting=False;self.completion_since=None
        self.retry_at=0;self.attempts=0
        self.transition('DASHBOARD','explicit '+mode+' selection',now)

    def transition(self,state,reason,now):
        if state not in STATES:raise ValueError('Invalid lifecycle state')
        self.reason=reason
        if state==self.state:return
        self.state=state;self.changed_at=now
        self.history.append({'at':now,'state':state,'reason':reason,'sessionPath':self.selected.get('path') if self.selected else None})
        self.history=self.history[-100:]

    def snapshot(self):
        return {'mode':self.mode,'state':self.state,'view':'live' if self.state in LIVE_STATES and self.presenting else 'dashboard',
                'selected':self.selected,'upcoming':self.upcoming,'reason':self.reason,'changedAt':self.changed_at,
                'lastTelemetryAt':self.last_live,'retryAt':self.retry_at,'retryAttempts':self.total_attempts,
                'circuit':self.circuit,'history':self.history[-20:]}

    def checkpoint(self):return {'schema':'session-controller-v1','mode':self.mode,'completed':self.completed[-100:],'history':self.history[-100:]}

    def tick(self,now,sessions,observation):
        if self.mode!='AUTO':return None
        if observation.get('dataMode')=='TEST':
            self.set_mode('MANUAL',now);return None
        valid=[]
        for s in sessions:
            start=utc_start(s)
            if start is not None and name(s.get('session')) in ('Practice 1','Practice 2','Practice 3','Sprint Qualifying','Sprint','Qualifying','Race') and s.get('path') not in self.completed:
                valid.append((start,s))
        valid.sort(key=lambda pair:pair[0])
        self.upcoming=next((s for t,s in valid if t>=now),None)
        eligible=[(t,s) for t,s in valid if now-43200<=t<=now+900]
        info=observation.get('session') or {}
        # A different actual feed identity must itself be a currently eligible
        # published provider session; no name-only/old-season substitution.
        actual=next((s for _,s in eligible if s.get('path') and identity_matches(s,info)),None)
        if self.selected and actual and actual.get('path')!=self.selected.get('path'):
            self.selected=None;self.last_live=None;self.presenting=False;self.completion_since=None;self.retry_at=0
        if self.state=='SESSION_COMPLETED':
            if now-self.changed_at<20:return None
            self.selected=None;self.last_live=None;self.presenting=False;self.completion_since=None
            self.transition('DASHBOARD','completion dwell finished',now)
            return 'stop'
        if self.selected is None:
            if not eligible:
                if self.upcoming and (utc_start(self.upcoming)-now)<=3600:self.transition('SESSION_APPROACHING','schedule advisory; not proof of activity',now)
                else:self.transition('DASHBOARD','no eligible session',now)
                return 'stop' if observation.get('sourceRunning') else None
            self.selected=(actual or eligible[-1][1]);self.attempts=0;self.retry_at=0
            self.transition('WAITING_FOR_SESSION','monitor window; validate published identity',now)
        selected=self.selected
        if not selected.get('path'):
            # Schedule may precede publication. Replace advisory only with an
            # actual matching provider entry on a later discovery poll.
            replacement=next((s for _,s in eligible if s.get('path') and s.get('advisoryId')==selected.get('advisoryId')),None)
            if replacement:self.selected=replacement;selected=replacement
            else:
                self.transition('WAITING_FOR_SESSION','schedule available; provider session not published',now);return None
        matches=identity_matches(selected,info)
        status=observation.get('status');red=observation.get('trackStatus')=='5'
        fresh=observation.get('freshGps',False) or observation.get('freshDelta',False)
        if matches and (status=='Finalised' or status in ('Finished','Ended','Ends') and not red):
            if self.completion_since is None:self.completion_since=now;self.completion_observations=0
            self.completion_observations+=1
            self.transition('LIVE_STALE' if self.presenting else 'WAITING_FOR_SESSION','provider completion pending confirmation',now)
            if now-self.completion_since>=10 and self.completion_observations>=2:
                self.completed=(self.completed+[selected['path']])[-100:]
                self.transition('SESSION_COMPLETED','provider '+status+' confirmed across observations',now)
            return None
        self.completion_since=None;self.completion_observations=0
        if matches and (red or status in ('Aborted','Suspended','Stopped')):
            self.presenting=True
            self.transition('SESSION_SUSPENDED','provider suspension/red flag; not completion',now)
            if fresh:self.last_live=now
        elif matches and fresh and (status in ('Started','Resumed') or status is None and observation.get('freshDelta')):
            self.last_live=now;self.presenting=True
            self.transition('LIVE' if observation.get('freshGps') else 'LIVE_STALE','matched identity and fresh measured telemetry',now)
        elif self.presenting:
            self.transition('RECOVERING' if not observation.get('sourceRunning') or observation.get('upstream') in ('disconnected','connecting','connection-error','authentication-error') else 'LIVE_STALE',
                            'transport recovery or telemetry gap; not completion',now)
        else:self.transition('CONNECTING' if observation.get('sourceRunning') else 'WAITING_FOR_SESSION','awaiting matching live identity/telemetry',now)
        quiet_live=matches and self.presenting and status in ('Started','Resumed') and not red and self.last_live is not None and now-self.last_live>60
        missing_identity=not matches and now>(utc_start(selected) or now)+30
        refresh=observation.get('sourceRunning') and (quiet_live or missing_identity) and now-self.last_attempt_at>=60
        needs_connection=refresh or not observation.get('sourceRunning') or ('expectedPath' in observation and observation['expectedPath']!=selected['path'])
        if needs_connection and now>=self.retry_at:
            self.last_attempt_at=now
            self.total_attempts+=1;self.attempts+=1
            delay=min(60,2**min(self.attempts,6))
            if self.attempts>=8:delay=300;self.attempts=0
            self.retry_at=now+delay
            self.transition('CONNECTING' if not self.presenting else 'RECOVERING','bounded subscription attempt',now)
            return 'connect'
        return None


def combine_schedule(published,advisories):
    """Advisory timestamps may schedule monitoring, never invent provider paths."""
    def norm(text):return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',str(text)).encode('ascii','ignore').decode().lower())
    published=list({s['path']:s for s in published if isinstance(s,dict) and s.get('path')}.values())
    def same_day(s,advice):
        a,b=utc_start(s),utc_start(advice)
        if a is not None and b is not None:return abs(a-b)<=43200
        try:return abs((datetime.fromisoformat(str(s.get('start'))[:10])-datetime.fromisoformat(advice['start'][:10])).days)<=1
        except ValueError:return False
    output=[];used=set()
    for advice in advisories:
        matches=[s for s in published if name(s.get('session'))==advice['session'] and
                 norm(s.get('location'))==norm(advice.get('location')) and same_day(s,advice)]
        if len(matches)==1:
            s=dict(matches[0]);s['advisoryId']=advice['advisoryId']
            if utc_start(s) is None:
                s['providerStartDate']=s['start'];s['start']=advice['start'];s['timeSource']='advisory UTC; identity from LiveF1'
            output.append(s);used.add(s['path'])
        elif not matches:output.append(advice)
    for s in published:
        if s.get('path') not in used and utc_start(s) is not None:output.append(s)
    unique={s.get('path') or s.get('advisoryId'):s for s in output}
    return list(unique.values())


def schedule_advisories(year):
    import requests
    url=f'https://api.jolpi.ca/ergast/f1/{year}.json?limit=100'
    with requests.get(url,timeout=(5,15),stream=True) as response:
        response.raise_for_status();body=bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body)>1024*1024:raise ValueError('Schedule metadata exceeds limit')
    data=json.loads(body)
    output=[]
    for race in data['MRData']['RaceTable']['Races']:
        mapping=[('FirstPractice','Practice 1'),('SecondPractice','Practice 2'),('ThirdPractice','Practice 3'),('SprintQualifying','Sprint Qualifying'),('SprintShootout','Sprint Qualifying'),('Sprint','Sprint'),('Qualifying','Qualifying'),(None,'Race')]
        for field,session in mapping:
            s=race.get(field,{}) if field else race
            if not s.get('date') or not s.get('time'):continue
            output.append({'year':year,'event':race['raceName'],'location':race['Circuit']['Location']['locality'],'session':session,
                           'start':s['date']+'T'+s['time'],'path':None,'advisoryId':race['round']+':'+session,'advisory':True})
    return output


def simulate():
    controller=SessionController();base=1770000000
    sessions=[{'path':'SIMULATION/'+kind,'start':datetime.fromtimestamp(base+4000+i*7200,timezone.utc).isoformat(),
               'session':kind,'circuit':{'Key':'SIMULATION'},'year':2026,'advisoryId':'sim:'+kind} for i,kind in enumerate(('Practice 1','Qualifying','Race'))]
    for selected in sessions:
        start=utc_start(selected);advice={**selected,'path':None}
        samples=[(-4000,{}),(-3500,{}),(-800,{}),(-600,{}),(0,{'sourceRunning':True,'session':{'Path':selected['path']},'freshGps':True,'status':'Started'}),
                 (10,{'sourceRunning':False}),(20,{'sourceRunning':True,'session':{'Path':selected['path']},'freshGps':True,'status':'Started'}),
                 (80,{'sourceRunning':True,'session':{'Path':selected['path']},'status':'Aborted','trackStatus':'5'}),
                 (90,{'sourceRunning':True,'session':{'Path':selected['path']},'freshGps':True,'status':'Started'}),
                 (100,{'sourceRunning':True,'session':{'Path':selected['path']},'status':'Finished'}),
                 (115,{'sourceRunning':True,'session':{'Path':selected['path']},'status':'Finished'}),(140,{})]
        for offset,observation in samples:
            available=[advice if s is selected and offset< -600 else s for s in sessions]
            action=controller.tick(start+offset,available,observation)
            print(json.dumps({'simulation':True,'session':selected['session'],'time':start+offset,'state':controller.state,'action':action,'reason':controller.reason}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--simulate',action='store_true',required=True);parser.parse_args();simulate()
