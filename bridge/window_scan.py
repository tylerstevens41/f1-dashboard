"""Bounded candidate discovery from measured lap timing and moving GPS.

This finds a window to test, never a verified lap or replacement trajectory.
Only count/timestamp summaries are returned; raw messages/coordinates stay local.
"""
import json
import math
import time
from urllib.parse import urljoin
from .archive import small_json, lines, split_stream_record, MAX_START_SECONDS
from .protocol import merge, decode, utc_ms


class ScanUnavailable(ValueError):
    def __init__(self, code):
        super().__init__('No usable geometry window found within the bounded source scan')
        self.code=code


def find_usable_window(path, after_seconds, diagnostics=None, max_records=200000, max_seconds=120, on_progress=lambda:None):
    stats=diagnostics if diagnostics is not None else {}
    stats.update(stage='timing',status='scanning',bytesRead=0,timingRecords=0,positionMessages=0,
                 positionRecords=0,zeroCoordinateRecords=0,invalidCoordinateRecords=0,
                 missingTimestampRecords=0,movingDrivers=0,timedDrivers=0,recordLimit=max_records)
    budget=[0];count=0;started=time.monotonic();last_report=started
    def limits():
        nonlocal last_report
        now=time.monotonic()
        stats['elapsedSeconds']=round(now-started,3);stats['bytesRead']=budget[0]
        if count>max_records or now-started>max_seconds:raise ScanUnavailable('scan-limit')
        if now-last_report>=2:
            on_progress();last_report=now
    try:
        feeds=small_json(path+'Index.json')['Feeds']
        timing=feeds.get('TimingData',{}).get('StreamPath')
        position=feeds.get('Position.z',{}).get('StreamPath')
        if not timing or not position:raise ScanUnavailable('missing-required-stream')
        state={};lap_times={}
        # First identify measured lap-number availability. Merely receiving
        # position packets (often 0,0 before a session) is not enough.
        for line in lines(urljoin(path,timing),budget):
            count+=1;stats['timingRecords']+=1
            limits()
            offset,text=split_stream_record(line)
            if offset/1000>MAX_START_SECONDS:break
            payload=json.loads(text)
            if not isinstance(payload,dict) or not isinstance(payload.get('Lines',{}),dict):
                raise ScanUnavailable('invalid-timing-schema')
            state=merge(state,payload.get('Lines',{}))
            for driver,row in state.items():
                if not isinstance(row,dict):continue
                lap=row.get('NumberOfLaps')
                if lap is None or isinstance(lap,bool) or not str(lap).isdigit() or int(lap)<1:continue
                if row.get('InPit') is True or row.get('PitOut') is True:continue
                lap_times.setdefault(driver,offset/1000)
            stats['timedDrivers']=len(lap_times)
            if len(lap_times)>=3:break
        if len(lap_times)<3:raise ScanUnavailable('no-lap-timing-in-bounded-source')
        stats['lapTimingStartSeconds']=max(lap_times.values())
        stats['stage']='position'
        previous={};moving=set()
        for line in lines(urljoin(path,position),budget):
            count+=1;stats['positionMessages']+=1
            limits()
            offset,text=split_stream_record(line);second=offset/1000
            stats['lastExaminedSourceSeconds']=second
            if second>MAX_START_SECONDS:break
            if second<max(after_seconds,min(lap_times.values())):continue
            records=decode('Position.z',json.loads(text))
            for driver,record in records.items():
                if driver not in lap_times or second<lap_times[driver]:continue
                for sample in record.get('_batch',[record]):
                    stats['positionRecords']+=1
                    x,y=sample.get('X'),sample.get('Y')
                    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (x,y)):
                        stats['invalidCoordinateRecords']+=1;continue
                    if x==0 and y==0:stats['zeroCoordinateRecords']+=1;continue
                    if str(sample.get('Status','')).lower() not in ('ontrack',''):continue
                    stamp=utc_ms(sample.get('Utc'))
                    if stamp is None:stats['missingTimestampRecords']+=1;continue
                    old=previous.get(driver)
                    if old and stamp>old[2] and (x!=old[0] or y!=old[1]):moving.add(driver)
                    if old is None or stamp>old[2]:previous[driver]=(x,y,stamp)
            stats['movingDrivers']=len(moving)
            if len(moving)>=3:
                stats.update(status='candidate',candidateOffset=int(math.floor(second)),
                             reason='measured lap numbers plus nonzero moving on-track GPS; full calibration still required')
                return stats['candidateOffset']
        raise ScanUnavailable('no-moving-gps-in-bounded-source')
    except Exception:
        stats['status']='failed'
        raise
    finally:
        stats['bytesRead']=budget[0]
