"""Slow metadata polling around the existing Bridge; one source subscription."""
import asyncio
from datetime import datetime,timezone
from pathlib import Path
import time
from .autonomous import SessionController,combine_schedule,schedule_advisories,utc_start
from .annotation_progress import atomic
from .diagnostics import safe_exception


class ControllerService:
    def __init__(self,bridge,path,force_mode=None):
        self.bridge=bridge;self.path=Path(path)
        saved={}
        if self.path.exists():
            try:
                from .preparation import read_json
                saved=read_json(self.path)
                if saved.get('schema')!='session-controller-v1':saved={}
            except (OSError,ValueError):pass
        self.machine=SessionController(saved)
        if force_mode:self.machine.set_mode(force_mode,time.time())
        cached=saved.get('sessions',[])
        self.sessions=[s for s in cached if isinstance(s,dict)][:256] if isinstance(cached,list) else []
        self.discovery_due=0;self.last_discovery=saved.get('lastDiscoveryAt');self.discovery_failures=0
        self.discovery_error=None;self.last_checkpoint=None;self.asset_token=None;self.asset_due=0
        self.discovery_task=None
        self.asset_error=None;self.last_asset_stamp=None

    def snapshot(self):
        return {**self.machine.snapshot(),'lastDiscoveryAt':self.last_discovery,'discoveryRetryAt':self.discovery_due,
                'circuitIdentity':{'year':self.asset_token[0],'key':self.asset_token[1]} if self.asset_token else None,
                'discoveryFailures':self.discovery_failures,'discoveryError':self.discovery_error,'assetError':self.asset_error}

    def persist(self):
        value={**self.machine.checkpoint(),'sessions':self.sessions[:256],'lastDiscoveryAt':self.last_discovery}
        if value!=self.last_checkpoint:
            atomic(self.path,value);self.last_checkpoint=value

    def mode(self,mode):
        if mode=='AUTO' and self.bridge.state.mode=='TEST':raise ValueError('TEST retained; switch to LIVE before explicitly enabling AUTO')
        self.machine.set_mode(mode,time.time());self.discovery_due=0
        if mode=='MANUAL' and self.discovery_task:self.discovery_task.cancel()
        self.persist()

    async def discover(self,now):
        from .archive import list_sessions
        year=datetime.fromtimestamp(now,timezone.utc).year
        try:
            # Independent metadata failures must not remove an already running feed.
            published=await asyncio.to_thread(list_sessions,year)
            self.sessions=combine_schedule(published,[])
            self.last_discovery=now;self.discovery_error=None;self.discovery_failures=0
            try:
                advice=await asyncio.to_thread(schedule_advisories,year)
                self.sessions=combine_schedule(published,advice)
            except Exception as exc:self.discovery_error={'schedule':safe_exception(exc,'identity')}
            near=any(utc_start(s) is not None and now-43200<=utc_start(s)<=now+3600 and s.get('path') not in self.machine.completed for s in self.sessions)
            self.discovery_due=now+(60 if near else 600)
        except Exception as exc:
            self.discovery_failures+=1;self.discovery_error=safe_exception(exc,'archive')
            self.discovery_due=now+min(600,30*2**min(self.discovery_failures-1,4))
            # A schedule can still show approaching/waiting while the actual
            # provider catalog is unavailable; it never fabricates a path.
            if not self.sessions:
                try:self.sessions=combine_schedule([],await asyncio.to_thread(schedule_advisories,year))
                except Exception:pass

    def observation(self,now):
        state=self.bridge.state;gps=state.topics.get('Position.z',{})
        fresh=any(isinstance(p,dict) and isinstance(p.get('_sampleTimeMs'),(int,float)) and
                  -2<=(now*1000-p['_sampleTimeMs'])/1000<=7.5 and
                  isinstance(p.get('X'),(int,float)) and isinstance(p.get('Y'),(int,float)) and
                  (p['X']!=0 or p['Y']!=0) for p in gps.values())
        delta=self.bridge.last_live_delta
        return {'session':state.topics.get('SessionInfo',{}),'status':state.topics.get('SessionStatus',{}).get('Status'),
                'trackStatus':str(state.topics.get('TrackStatus',{}).get('Status','')),'dataMode':state.mode,
                'upstream':state.upstream,'expectedPath':(self.bridge.live_expected or {}).get('path'),'sourceRunning':bool(self.bridge.source_task and not self.bridge.source_task.done()),
                'freshGps':fresh,'freshDelta':delta is not None and 0<=now-delta<=15}

    async def tick(self,now=None):
        now=time.time() if now is None else now
        if self.machine.mode!='AUTO':return
        if self.bridge.state.mode=='TEST':self.machine.set_mode('MANUAL',now);self.persist();return
        if now>=self.discovery_due and (self.discovery_task is None or self.discovery_task.done()):
            self.discovery_task=asyncio.create_task(self.discover(now))
        async with self.bridge.control_lock:
            if self.machine.mode!='AUTO' or self.bridge.state.mode=='TEST':return
            action=self.machine.tick(now,self.sessions,self.observation(now))
            if action=='connect':await self.bridge.start_live(self.machine.selected)
            elif action=='stop':
                await self.bridge.stop_source();self.bridge.state.reset('LIVE');self.bridge.error=None
                self.bridge.state.upstream='idle';await self.bridge.broadcast(self.bridge.snapshot())
            info=self.bridge.state.topics.get('SessionInfo',{})
            key=info.get('Meeting',{}).get('Circuit',{}).get('Key')
            year=str(info.get('StartDate',''))[:4]
            token=(year,key)
            if key is not None and year.isdigit() and (token!=self.asset_token or now>=self.asset_due):
                self.asset_token=token;self.asset_due=now+60
                try:
                    asset=await asyncio.to_thread(self.bridge.asset_store.lookup,int(year),None,key)
                    # Existing public Austin reference must not be replaced.
                    short=str(info.get('Meeting',{}).get('Circuit',{}).get('ShortName','')).lower()
                    self.machine.circuit='public-reference' if short in ('austin','cota','circuit of the americas') else 'available' if asset else 'missing; preparation deferred outside active telemetry'
                    self.asset_error=None
                    stamp=(token,asset.get('geometryId'),bool(asset.get('corners')),bool(asset.get('sectors'))) if asset else None
                    if asset and stamp!=self.last_asset_stamp:
                        self.last_asset_stamp=stamp
                        await self.bridge.broadcast({'version':1,'type':'circuit-assets','bundle':asset})
                except Exception as exc:self.asset_error=safe_exception(exc,'cache');self.machine.circuit='asset-error'
            self.persist()

    async def run(self):
        while True:
            try:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.discovery_error=safe_exception(exc,'identity');self.discovery_due=max(self.discovery_due,time.time()+30)
                await asyncio.sleep(5)
            await asyncio.sleep(2)

    async def close(self):
        if self.discovery_task:
            self.discovery_task.cancel()
            await asyncio.gather(self.discovery_task,return_exceptions=True)
