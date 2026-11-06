"""Pure stdlib progress/checkpoints, usable in both isolated environments."""
from datetime import datetime,timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from .diagnostics import safe_exception

PHASES={'telemetry-full-reload','telemetry-readiness','http-request','fastf1-authentication-required','session-info-load','driver-list-load','session-status-load','lap-count-load','track-status-load','timing-data-load','timing-data-parse','timing-app-load','fastf1-import','starting','source-cache','fastf1-cache-open','fastf1-cache-prune','fastf1-session-retrieval','fastf1-laps-load',
        'corner-metadata-retrieval','corner-metadata-distances','fastf1-telemetry-load',
        'car-data-download','car-data-parse','position-data-download','position-data-parse','car-data-cache','position-data-cache',
        'reference-lap-position','source-save','corner-registration','corners-checkpoint',
        'multi-lap-collection','sector-calculation','sectors-checkpoint','complete'}


def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(value,allow_nan=False,separators=(',',':'))
    if len(text)>32*1024*1024:raise ValueError('Annotation checkpoint exceeds 32 MiB')
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.annotation-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf8') as handle:
            handle.write(text);handle.flush();os.fsync(handle.fileno())
        # Windows readers/security scanners may briefly hold the destination
        # without FILE_SHARE_DELETE. Keep the complete temp file and old target
        # intact while retrying only known Windows access/sharing violations.
        for attempt in range(6):
            try:
                os.replace(temp,path)
                break
            except PermissionError as exc:
                if getattr(exc,'winerror',None) not in {5,32,33} or attempt==5:raise
                time.sleep(min(.02*2**attempt,.2))
    finally:Path(temp).unlink(missing_ok=True)


class Progress:
    def __init__(self,path):
        self.path=Path(path);self.started=time.monotonic();self.phase_tick=self.started;self.events=[]
        self.value={'schema':'fastf1-annotation-diagnostics-v1','startedAt':time.time(),'phase':'starting','phaseStartedAt':time.time(),'state':'running','events':self.events,'phaseDurationsSeconds':{}}
        self.event('starting')

    def event(self,phase,**counts):
        if phase not in PHASES:raise ValueError('Unknown annotation phase')
        now=time.time()
        allowed={k:v for k,v in counts.items() if k in {'inspected','accepted','rejected','corners','metadataCorners','sourceCacheHit','checkpointHit','httpStatus','cacheHit','requestSeconds','positionDrivers','usablePositionDrivers'} and isinstance(v,(bool,int,float))}
        for key,values in {'endpointKind':{'SessionInfo','DriverList','SessionStatus','LapCount','TrackStatus','TimingData','TimingAppData','Position','CarData','Index','live-timing','race-results','circuit-metadata','other-upstream'},'requestState':{'started','completed','failed'},'exceptionType':{'Timeout','ReadTimeout','ConnectTimeout','ConnectionError','FastF1AuthenticationRequired','RequestError'}}.items():
            if counts.get(key) in values:allowed[key]=counts[key]
        if phase=='http-request' and counts.get('requestState')=='started':
            for key in ('httpStatus','cacheHit','exceptionType','requestSeconds'):self.value.pop(key,None)
        if self.value['phase']!=phase:
            previous=self.value['phase'];durations=self.value['phaseDurationsSeconds']
            durations[previous]=round(durations.get(previous,0)+time.monotonic()-self.phase_tick,3)
            self.phase_tick=time.monotonic();self.value['phaseStartedAt']=now
        self.events.append({'at':datetime.now(timezone.utc).isoformat(),'elapsedSeconds':round(time.monotonic()-self.started,3),'phase':phase,**allowed})
        self.events[:]=self.events[-200:]
        self.value.update(phase=phase,updatedAt=now,elapsedSeconds=round(time.monotonic()-self.started,3),**allowed)
        atomic(self.path,self.value)

    def failure(self,exc):
        self.value.update(state='failed',failedPhase=self.value['phase'],error=safe_exception(exc,'annotations'),updatedAt=time.time())
        atomic(self.path,self.value)

    def finish(self,corners,sectors):
        failed=self.value.get('error')
        self.event('complete')
        self.value.update(state='complete' if corners and sectors else 'incomplete',cornersReady=bool(corners),sectorsReady=bool(sectors))
        if failed:self.value['error']=failed
        atomic(self.path,self.value)


class FastF1Stages(logging.Handler):
    """Only exact library literals; never format or export logging arguments."""
    stages={'Fetching session info data...':'session-info-load','Fetching driver list...':'driver-list-load','Fetching session status data...':'session-status-load','Fetching lap count data...':'lap-count-load','Fetching track status data...':'track-status-load','Fetching timing data...':'timing-data-load','Parsing timing data...':'timing-data-parse','Fetching timing app data...':'timing-app-load','Fetching car data...':'car-data-download','Parsing car data...':'car-data-parse',
            'Fetching position data...':'position-data-download','Parsing position data...':'position-data-parse',
            'Using cached data for car_data':'car-data-cache','Using cached data for position_data':'position-data-cache'}
    def __init__(self,report):super().__init__();self.report=report
    def emit(self,record):
        if isinstance(record.msg,str) and record.msg in self.stages:
            self.report(self.stages[record.msg])
