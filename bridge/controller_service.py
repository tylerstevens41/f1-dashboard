"""Slow metadata polling around the existing Bridge; one source subscription."""
import asyncio
from datetime import datetime,timezone
from pathlib import Path
import time
import math
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
                if not isinstance(saved,dict) or saved.get('schema')!='session-controller-v1':saved={}
            except (OSError,ValueError):pass
        self.machine=SessionController(saved)
        if force_mode:self.machine.set_mode(force_mode,time.time())
        cached=saved.get('sessions',[])
        self.sessions=[s for s in cached if isinstance(s,dict)][:256] if isinstance(cached,list) else []
        self.discovery_due=0;self.last_discovery=saved.get('lastDiscoveryAt');self.discovery_failures=0
        self.discovery_error=None;self.last_checkpoint=None;self.asset_token=None;self.asset_due=0
        self.discovery_task=None
        self.asset_error=None;self.last_asset_stamp=None;self.last_presentation=None
        self.published=[];self.identity_task=None;self.identity_token=None;self.provider_identity=None
        self.identity_due=0;self.identity_failures=0;self.identity_check={'state':'not-requested'}

    def snapshot(self):
        state=self.bridge.state
        info=state.topics.get('SessionInfo',{})
        status=state.topics.get('SessionStatus',{}).get('Status')
        # A manual LIVE command owns the shared feed. A read-only wall mirrors
        # that requested session (including waiting/recovery UI), never TEST.
        # This is a view choice, not an assertion of fresh GPS or active racing.
        ended=status=='Finalised' or status in ('Finished','Ended','Ends') and str(state.topics.get('TrackStatus',{}).get('Status',''))!='5'
        manual_live=(self.machine.mode=='MANUAL' and state.mode=='LIVE' and bool(info) and
                     self.bridge.live_confirmed and not ended)
        return {**self.machine.snapshot(),'manualPresentation':'live' if manual_live else 'dashboard',
                'feedEvidence':{'dataMode':state.mode,'identityConfirmed':self.bridge.live_confirmed,
                                'sessionPath':info.get('Path'),'sessionStatus':status,
                                'sourceRunning':bool(self.bridge.source_task and not self.bridge.source_task.done())},
                'lastDiscoveryAt':self.last_discovery,'discoveryRetryAt':self.discovery_due,
                'circuitIdentity':{'year':self.asset_token[0],'key':self.asset_token[1]} if self.asset_token else None,
                'discoveryFailures':self.discovery_failures,'discoveryError':self.discovery_error,'assetError':self.asset_error,
                'providerIdentityCheck':self.identity_check,
                'catalogDiagnostics':{'source':'yearly-archive-index','publishedEntries':len(self.published),
                    'entriesWithUsableStart':sum(utc_start(s) is not None for s in self.published),
                    'feedPathEntries':sum(s.get('path')==info.get('Path') for s in self.published),
                    'feedPathEntriesWithUsableStart':sum(s.get('path')==info.get('Path') and utc_start(s) is not None for s in self.published),
                    'controllerPathCandidates':sum(bool(s.get('path')) for s in self.sessions)}}

    def persist(self):
        value={**self.machine.checkpoint(),'sessions':self.sessions[:256],'lastDiscoveryAt':self.last_discovery}
        if value!=self.last_checkpoint:
            atomic(self.path,value);self.last_checkpoint=value

    def mode(self,mode):
        if mode=='AUTO' and self.bridge.state.mode=='TEST':raise ValueError('TEST retained; switch to LIVE before explicitly enabling AUTO')
        self.machine.set_mode(mode,time.time());self.discovery_due=0
        if mode=='MANUAL':
            if self.discovery_task:self.discovery_task.cancel()
            if self.identity_task:self.identity_task.cancel()
        self.persist()

    async def discover(self,now):
        from .archive import list_sessions
        year=datetime.fromtimestamp(now,timezone.utc).year
        try:
            # Independent metadata failures must not remove an already running feed.
            published=await asyncio.to_thread(list_sessions,year)
            self.published=published
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
                  all(isinstance(p.get(k),(int,float)) and not isinstance(p[k],bool) and math.isfinite(p[k]) for k in ('X','Y')) and
                  (p['X']!=0 or p['Y']!=0) for p in gps.values())
        delta=self.bridge.last_live_delta
        return {'session':state.topics.get('SessionInfo',{}),'status':state.topics.get('SessionStatus',{}).get('Status'),
                'trackStatus':str(state.topics.get('TrackStatus',{}).get('Status','')),'dataMode':state.mode,
                'identityConfirmed':self.bridge.live_confirmed,
                'upstream':state.upstream,'expectedPath':(self.bridge.live_expected or {}).get('path'),'sourceRunning':bool(self.bridge.source_task and not self.bridge.source_task.done()),
                'freshGps':fresh,'freshDelta':delta is not None and 0<=now-delta<=15}

    async def confirm_provider_identity(self,token,now):
        from .live_reconciliation import published_session_info
        started=time.monotonic()
        try:
            result=await asyncio.to_thread(published_session_info,token[0])
            if token==self.identity_token:
                checked=now+max(0,time.monotonic()-started)
                self.provider_identity=result;self.identity_failures=0;self.identity_due=checked+60
                self.identity_check={'state':'received','path':token[0],'checkedAt':checked}
        except asyncio.CancelledError:raise
        except Exception as exc:
            if token==self.identity_token:
                checked=now+max(0,time.monotonic()-started)
                self.identity_failures+=1;self.identity_due=checked+min(300,30*2**min(self.identity_failures-1,4))
                self.identity_check={'state':'unavailable','path':token[0],'checkedAt':checked,
                                     'retryAt':self.identity_due,'error':safe_exception(exc,'archive')}

    def reconciliation_observation(self,now):
        from .live_reconciliation import reconcile
        observation=self.observation(now)
        observation['publishedSessions']=self.published
        pending=self.machine.selected
        if not pending or pending.get('path'):return observation
        info=observation['session'];meeting=info.get('Meeting',{});circuit=meeting.get('Circuit',{})
        token=(info.get('Path'),info.get('Key'),meeting.get('Key'),circuit.get('Key'),info.get('StartDate'))
        if token!=self.identity_token:
            if self.identity_task:self.identity_task.cancel()
            self.identity_token=token;self.provider_identity=None;self.identity_due=0;self.identity_failures=0
            self.identity_check={'state':'not-requested'}
        observation['providerIdentity']=self.provider_identity
        _,check=reconcile(now,pending,observation,self.provider_identity,self.published)
        if check.get('source')=='year-index':self.identity_check={'state':'year-index-confirmed','path':token[0],'checkedAt':now}
        if (check['status']=='provider-confirmation-required' or check.get('reason','').startswith('provider-document-')) and now>=self.identity_due and (self.identity_task is None or self.identity_task.done()):
            self.identity_check={'state':'checking','path':token[0],'requestedAt':now}
            self.identity_task=asyncio.create_task(self.confirm_provider_identity(token,now))
        return observation

    async def tick(self,now=None):
        now=time.time() if now is None else now
        if self.machine.mode!='AUTO':return
        if self.bridge.state.mode=='TEST':self.mode('MANUAL');return
        if now>=self.discovery_due and (self.discovery_task is None or self.discovery_task.done()):
            self.discovery_task=asyncio.create_task(self.discover(now))
        async with self.bridge.control_lock:
            if self.machine.mode!='AUTO' or self.bridge.state.mode=='TEST':return
            observation=self.reconciliation_observation(now)
            action=self.machine.tick(now,self.sessions,observation)
            selected=self.machine.selected or {}
            if (selected.get('identitySource') in ('live-feed-plus-independent-session-metadata','live-feed-plus-year-index') and
                self.machine.reconciliation.get('status')=='verified-current-provider-session' and
                self.machine.state in ('LIVE','LIVE_STALE') and observation.get('identityConfirmed') and
                (observation.get('freshGps') or observation.get('freshDelta')) and
                observation['session'].get('Path')==selected.get('path')):
                # Bind the independently verified identity to the existing
                # source. No stop/start or additional LiveF1 subscription.
                if self.bridge.live_expected is None:self.bridge.live_expected=selected
                if not any(s.get('path')==selected['path'] for s in self.sessions):self.sessions.append(dict(selected))
            if action=='connect':await self.bridge.start_live(self.machine.selected)
            elif (not action and self.machine.selected and not self.machine.selected.get('path') and
                  not observation.get('sourceRunning') and now>=self.machine.retry_at and
                  utc_start(self.machine.selected) is not None and
                  now-43200<=utc_start(self.machine.selected)<=now+900):
                # Cold start / restart: a year index can lag the live service.
                # Observe its one current source without inventing an expected
                # path; remain Dashboard until independent reconciliation passes.
                self.machine.request_connection(now,observe=True)
                await self.bridge.start_live(None)
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
            presentation=self.machine.snapshot()
            marker=(presentation['mode'],presentation['state'],presentation['view'],presentation['reason'],
                    (presentation['selected'] or {}).get('path'),presentation['circuit'])
            if marker!=self.last_presentation:
                self.last_presentation=marker
                # Publish transitions explicitly on the existing control channel;
                # heartbeat also carries this snapshot for reconnect/refresh.
                await self.bridge.broadcast(self.bridge.transport_message('status',error=self.bridge.error))

    async def run(self):
        while True:
            try:await self.tick()
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.discovery_error=safe_exception(exc,'identity');self.discovery_due=max(self.discovery_due,time.time()+30)
                await asyncio.sleep(5)
            await asyncio.sleep(2)

    async def close(self):
        tasks=[task for task in (self.discovery_task,self.identity_task) if task]
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
