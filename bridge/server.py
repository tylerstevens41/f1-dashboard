"""Local-only LIVE/TEST bridge. Run `python -m bridge.server --help`."""
import argparse
import asyncio
import copy
import json
import logging
import time
from datetime import datetime, timezone

from websockets.asyncio.server import serve
from .archive import fetch_clip, list_sessions, load_recording, save_clip
from .protocol import TOPICS, RaceState, merge
from .playback_clock import PlaybackClock
from .autonomous import name as session_name


class Bridge:
    def __init__(self, allow_test=False, recording=None):
        self.state = RaceState()
        self.clients = set()
        self.source_task = None
        self.control_lock = asyncio.Lock()
        self.allow_test = allow_test
        self.error = None
        self.live_expected = None
        self.live_confirmed = True
        self.recording_path = recording
        self.recording = None
        self.record_started = None
        self.clip = None
        self.timeline = None
        self.gps_seen={}
        self.gps_diagnostics={'rawMessages':0,'rawReceivedUtcMs':None,'normalizedReceivedUtcMs':None,'lastSampleUtcMs':None,'identityDrops':0,'parseErrors':0,'subscriptionSnapshots':0,'connectionAttempts':0,'connectionLosses':0}
        self.offset = 0
        self.last_live_delta=None
        self.pending_live_delta=None
        self.autonomy=None
        self.last_tick = time.monotonic()

    def configure_preparation(self, root=None, enabled=False):
        from .preparation import AssetStore
        self.asset_store = AssetStore(root) if root else AssetStore()
        self.allow_prepare = enabled
        self.preparation_tasks = {}
        self.preparation_lock = asyncio.Lock()
        self.session_catalog = {}

    async def circuit_command(self, client, command):
        from .preparation import identity, PreparationError
        if not hasattr(self, 'asset_store'):
            self.configure_preparation()
        try:
            path = command.get('path')
            year = int(command.get('year', datetime.now(timezone.utc).year))
            info = self.state.topics.get('SessionInfo', {})
            key = str(info.get('Meeting', {}).get('Circuit', {}).get('Key'))
            bundle = await asyncio.to_thread(self.asset_store.lookup, year, path, None if path else key)
            if bundle:
                meta = bundle['identity']
                session = {'path':meta['path'], 'year':meta['year'], 'event':meta['event'], 'session':meta['session'],
                           'circuit':{'Key':meta['circuitKey'], 'ShortName':meta['name']}}
            else:
                if year not in self.session_catalog:
                    self.session_catalog[year] = await asyncio.to_thread(list_sessions, year)
                catalog = self.session_catalog[year]
                if path:
                    matches = [s for s in catalog if s['path'] == path]
                else:
                    matches = [s for s in catalog if str(s.get('circuit', {}).get('Key')) == key and s.get('session') == 'Race']
                if len(matches) != 1:
                    raise PreparationError('Select a published session with stable circuit metadata; no season/layout fallback was used')
                session = matches[0]
                meta = identity(session)
                bundle = await asyncio.to_thread(self.asset_store.get, meta)
            if bundle:
                await self.send(client, {'version':1, 'type':'circuit-assets', 'bundle':bundle})
            task = self.preparation_tasks.get(meta['assetKey'])
            if command['action'] == 'circuit-prepare' and not (task and not task.done()):
                if not self.allow_prepare:
                    raise PreparationError('Restart backend with --allow-prepare to enable local preparation')
                if meta['id'] == 'austin':
                    raise PreparationError('Austin uses the existing local reference assets; automatic preparation will not replace them')
                task = asyncio.create_task(self.prepare_circuit(session))
                self.preparation_tasks[meta['assetKey']] = task
            job_file = self.asset_store.directory(meta['assetKey']) / 'job.json'
            from .preparation import read_json
            job = read_json(job_file) if job_file.exists() else {}
            active = bool(task and not task.done())
            if job.get('state') in ('preparing','geometry-ready') and not active:
                job = {**job, 'state':'interrupted', 'error':'Previous preparation interrupted. Cached geometry is retained; retry to continue.'}
            await self.send(client, {'version':1, 'type':'circuit-job', 'job':{
                **job, 'identity':meta, 'state': 'preparing' if active else job.get('state','ready' if bundle else 'missing'),
                'enabled':self.allow_prepare, 'complete':bool(bundle and bundle.get('complete'))}})
        except Exception as exc:
            safe = str(exc) if isinstance(exc, PreparationError) else 'Circuit lookup unavailable. Check local archive authentication and metadata.'
            await self.send(client, {'version':1, 'type':'circuit-job', 'job':{'state':'failed','path':command.get('path'),'error':safe}})

    async def prepare_circuit(self, session):
        from .preparation import prepare, PreparationError
        loop = asyncio.get_running_loop()
        def report(**job):
            # The worker never changes race state, playback clocks or source tasks.
            asyncio.run_coroutine_threadsafe(self.preparation_progress(job), loop).result()
        async with self.preparation_lock:
            try:
                await asyncio.to_thread(prepare, session, self.asset_store, report, True)
            except PreparationError:
                pass  # sanitized failure already persisted/broadcast by coordinator
            except Exception:
                await self.broadcast({'version':1,'type':'circuit-job','job':{'state':'failed','path':session['path'],'error':'Preparation failed; existing assets retained.'}})

    async def preparation_progress(self, job):
        await self.broadcast({'version':1,'type':'circuit-job','job':job})
        if job.get('stage') in ('geometry','ready','annotation-checkpoint'):
            bundle = await asyncio.to_thread(self.asset_store.get, job['identity'])
            if bundle:
                await self.broadcast({'version':1,'type':'circuit-assets','bundle':bundle})

    async def send(self, client, message):
        try:
            await asyncio.wait_for(client.send(json.dumps(message, allow_nan=False)), timeout=2)
        except Exception:
            self.clients.discard(client)
            await client.close()

    async def broadcast(self, message):
        await asyncio.gather(*(self.send(client, message) for client in tuple(self.clients)))

    def playback_info(self):
        if not self.clip:
            return {}
        return {'offsetMs':self.offset,'durationMs':self.clip['durationMs'],
                'archiveStartSeconds':self.clip.get('startOffsetSeconds'),
                'sessionPath':self.clip.get('sessionPath')}

    def stamp_transport(self, message):
        now=time.monotonic()
        info=self.playback_info()
        if self.state.mode == 'TEST' and self.clip and self.timeline:
            offset=self.timeline.value(now)
            message['clockMs']=self.clip['originMs']+offset
            info={**info,'offsetMs':offset}
        elif self.state.mode == 'LIVE':
            message['clockMs']=datetime.now(timezone.utc).timestamp()*1000
        if self.autonomy and message.get('type') in ('snapshot','status'):message['controller']=self.autonomy.snapshot()
        if message.get('type') in ('snapshot','status') and self.state.mode=='LIVE':message['liveDiagnostics']=dict(self.gps_diagnostics)
        message['transportMs']=now*1000
        message['playbackInfo']=info
        return message

    def transport_message(self, kind, **extra):
        return self.stamp_transport(self.state.envelope(kind,**extra))

    def snapshot(self):
        return self.stamp_transport(self.state.snapshot())

    async def status(self, status):
        if status=='connecting':self.gps_diagnostics['connectionAttempts']+=1
        if status in ('disconnected','connection-error','authentication-error'):self.gps_diagnostics['connectionLosses']+=1
        self.state.upstream = status
        await self.broadcast(self.transport_message('status', error=self.error, playbackInfo=self.playback_info()))

    async def emit(self, topic, payload, timestamp=None, clock_ms=None):
        if topic not in TOPICS:
            return
        if self.state.mode=='LIVE' and topic=='Position.z':
            self.gps_diagnostics['rawMessages']+=1;self.gps_diagnostics['rawReceivedUtcMs']=datetime.now(timezone.utc).timestamp()*1000
        if self.state.mode=='LIVE' and self.live_expected:
            if topic=='SessionInfo':
                expected=self.live_expected
                info=merge(self.state.topics.get('SessionInfo',{}),payload) if isinstance(payload,dict) else {}
                actual=info.get('Path')
                if actual is not None or (info.get('StartDate')):
                    self.live_confirmed=(actual==expected['path']) if actual is not None else (
                        str(info.get('Meeting',{}).get('Circuit',{}).get('Key'))==str(expected['circuit']['Key']) and
                        session_name(info.get('Name'))==session_name(expected['session']) and str(info['StartDate'])[:10]==str(expected.get('providerStartDate',expected['start']))[:10])
                    self.error=None if self.live_confirmed else 'The current LIVE feed is not the selected session. Waiting; no archive substitution.'
                    await self.status('connected' if self.live_confirmed else 'waiting-session')
            elif not self.live_confirmed:
                if topic=='Position.z':self.gps_diagnostics['identityDrops']+=1
                return
        if self.recording_path and self.state.mode == 'LIVE':
            self.capture(topic, payload)
        try:
            messages = self.state.ingest(topic, payload, timestamp, clock_ms)
        except (ValueError, KeyError, TypeError):
            if topic=='Position.z':self.gps_diagnostics['parseErrors']+=1
            self.error = f'Invalid {topic} update; retained previous state.'
            await self.broadcast(self.transport_message('status', error=self.error, playbackInfo=self.playback_info()))
            return
        if self.state.mode=='LIVE' and topic=='Position.z':
            positions=self.state.topics.get('Position.z',{})
            valid=[r.get('_sampleTimeMs') for r in positions.values() if isinstance(r,dict) and isinstance(r.get('_sampleTimeMs'),(int,float))]
            newest=max(valid) if valid else None
            changed=0
            for number,record in positions.items():
                sample=record.get('_sampleTimeMs') if isinstance(record,dict) else None
                if isinstance(sample,(int,float)) and sample>self.gps_seen.get(number,float('-inf')):
                    self.gps_seen[number]=sample;changed+=1
            if changed:self.gps_diagnostics['normalizedReceivedUtcMs']=datetime.now(timezone.utc).timestamp()*1000
            self.gps_diagnostics['lastSampleUtcMs']=newest
            self.gps_diagnostics['normalizedNewDrivers']=changed
            self.gps_diagnostics['driversWithoutUtcHistory']=sum(not r.get('_history') for r in positions.values() if isinstance(r,dict))
            self.gps_diagnostics['normalizedDrivers']=len(valid)
            self.gps_diagnostics['coordinateRejects']=sum(r.get('_rejectedSamples',0) for r in positions.values() if isinstance(r,dict))
        if self.state.mode=='LIVE' and self.pending_live_delta==topic:
            if any(message.get('type')=='topic' for message in messages):self.last_live_delta=time.time()
            self.pending_live_delta=None
        for message in messages:
            await self.broadcast(message)

    def capture(self, topic, payload):
        now = time.monotonic()
        if self.recording is None:
            self.record_started = now
            self.recording = {'format':'livef1-clip-v1', 'source':'LiveF1',
                              'originMs': datetime.now(timezone.utc).timestamp()*1000,
                              'sessionPath': self.state.session_id, 'clockBasis':'receipt-utc', 'initial':copy.deepcopy(self.state.topics),
                              'capabilities':{}, 'events':[], 'durationMs':1}
        elapsed = (now-self.record_started)*1000
        if elapsed > 120000 or len(self.recording['events']) >= 30000:
            return
        size = len(json.dumps(payload))
        if size > 2*1024*1024:
            return
        used = self.recording.get('_bytes',0) + size
        if used > 32*1024*1024:
            return
        self.recording['_bytes'] = used
        self.recording['events'].append({'offsetMs':elapsed,'topic':topic,'payload':copy.deepcopy(payload)})
        self.recording['durationMs'] = max(1,elapsed)
        self.recording['capabilities'][topic] = 'captured'

    async def stop_source(self):
        if self.source_task:
            self.source_task.cancel()
            try:
                await self.source_task
            except asyncio.CancelledError:
                pass
            self.source_task = None

    async def start_live(self, expected=None):
        await self.stop_source()
        self.clip = None
        self.timeline = None
        self.live_expected=expected
        self.live_confirmed=expected is None
        self.state.reset('LIVE')
        self.error = None
        await self.broadcast(self.snapshot())
        self.source_task = asyncio.create_task(self.run_live())

    async def note_live_activity(self,topic):
        if self.state.mode=='LIVE' and topic in ('Position.z','TimingData','CarData.z'):
            self.pending_live_delta=topic

    async def begin_live_snapshot(self):
        self.pending_live_delta=None
        self.last_live_delta=None
        self.gps_seen={}
        self.gps_diagnostics['subscriptionSnapshots']+=1
        self.gps_diagnostics.update(rawReceivedUtcMs=None,normalizedReceivedUtcMs=None,lastSampleUtcMs=None)
        self.live_confirmed=self.live_expected is None
        self.state.reset('LIVE')
        self.state.upstream = 'connected'
        await self.broadcast(self.snapshot())

    async def run_live(self):
        try:
            from .live import DashboardClient
            client = DashboardClient(self.emit, self.status, self.begin_live_snapshot,self.note_live_activity)
            await client._run()  # pinned LiveF1 1.3.0 transport; see docs
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = 'LiveF1 connection failed. Verify backend login locally; no credentials are sent to the browser.'
            await self.status('authentication-error' if type(exc).__name__=='AuthenticationError' else 'connection-error')

    async def start_clip(self, clip):
        if self.autonomy:self.autonomy.mode('MANUAL')
        await self.stop_source()
        self.clip = clip
        self.timeline = PlaybackClock(clip['durationMs'],time.monotonic())
        self.offset = 0
        self.state.reset('TEST')
        self.state.topics = copy.deepcopy(clip['initial'])
        self.state.session_id = str(self.state.topics.get('SessionInfo', {}).get('Key') or clip.get('sessionPath') or 'recording')
        self.state.capabilities = clip.get('capabilities',{})
        self.state.freshness = clip.get('initialFreshness',{})
        self.state.clock_basis = clip.get('clockBasis', 'receipt-utc')
        self.state.clock_ms = clip['originMs']
        self.state.upstream = 'archive-ready'
        self.state.playback = 'paused'
        self.error = None
        await self.broadcast(self.snapshot())
        self.last_tick = time.monotonic()
        self.source_task = asyncio.create_task(self.play_clip())

    async def play_clip(self):
        index = 0
        while self.clip and self.offset < self.clip['durationMs']:
            now = time.monotonic()
            if self.state.playback == 'playing':
                self.offset = self.timeline.value(now)
                self.state.clock_ms = self.clip['originMs'] + self.offset
                while index < len(self.clip['events']) and self.clip['events'][index]['offsetMs'] <= self.offset:
                    event = self.clip['events'][index]
                    await self.emit(event['topic'], event['payload'], clock_ms=self.clip['originMs']+event['offsetMs'])
                    index += 1
                self.state.clock_ms = self.clip['originMs'] + self.offset
            self.last_tick = now
            if self.state.playback == 'playing':
                await self.broadcast(self.transport_message('clock',playbackInfo=self.playback_info()))
            await asyncio.sleep(0.025)
        self.timeline.control(time.monotonic(),running=False)
        self.state.playback = 'ended'
        await self.broadcast(self.transport_message('status', playbackInfo=self.playback_info()))

    async def heartbeat(self):
        while True:
            if self.state.mode == 'LIVE':
                self.state.clock_ms = datetime.now(timezone.utc).timestamp()*1000
            await self.broadcast(self.transport_message('status', error=self.error, playbackInfo=self.playback_info()))
            await asyncio.sleep(1)

    async def command(self, client, command):
        if command.get('action')=='controller-mode':
            try:
                if not self.autonomy:raise ValueError('Controller unavailable')
                self.autonomy.mode(command.get('mode'));await self.broadcast(self.snapshot())
            except Exception:
                await self.send(client,{'version':1,'type':'control-error','error':'Controller mode rejected. TEST is retained: switch to LIVE first before enabling AUTO.'})
            return
        if self.autonomy and command.get('action') in ('live','live-stop','load','play','pause','speed'):
            self.autonomy.mode('MANUAL')
        if command.get('action') in ('circuit-lookup','circuit-prepare'):
            await self.circuit_command(client, command)
            return
        if command.get('action') in ('live','live-stop','live-sessions'):
            async with self.control_lock:
                try:
                    action=command['action']
                    if action=='live-sessions':
                        year=datetime.now(timezone.utc).year
                        sessions=await asyncio.to_thread(list_sessions,year)
                        today=datetime.now(timezone.utc).date()
                        candidates=[]
                        for session in sessions:
                            if session.get('session')!='Race':continue
                            try:date=datetime.fromisoformat(session['start'].replace('Z','+00:00')).date()
                            except (ValueError,TypeError,KeyError):continue
                            if abs((date-today).days)<=1:candidates.append(session)
                        await self.send(client,{'version':1,'type':'live-sessions','sessions':candidates})
                    elif action=='live-stop':
                        if self.state.mode!='LIVE':raise ValueError('LIVE not active')
                        await self.stop_source();self.state.reset('LIVE');self.error=None
                        self.live_expected=None;self.live_confirmed=True
                        self.clip=None;self.timeline=None
                        self.state.upstream='disconnected';await self.broadcast(self.snapshot())
                    else:
                        expected=None
                        if command.get('path'):
                            year=datetime.now(timezone.utc).year
                            sessions=await asyncio.to_thread(list_sessions,year)
                            matches=[s for s in sessions if s['path']==command['path'] and s.get('session')=='Race']
                            if len(matches)!=1:raise ValueError('Requested session not published')
                            expected=matches[0]
                        await self.start_live(expected)
                except Exception as exc:
                    code=getattr(exc,'code',None)
                    error='LIVE authentication unavailable. Run backend --login locally.' if code=='authentication-required' else 'LIVE control/discovery unavailable. Retry; current feed has not been replaced with archive data.'
                    await self.send(client,{'version':1,'type':'control-error','error':error})
            return
        if not self.allow_test:
            await self.send(client, {'version':1,'type':'control-error','error':'TEST controls are disabled on this bridge.'})
            return
        async with self.control_lock:
            try:
                action = command.get('action')
                if action == 'sessions':
                    sessions = await asyncio.to_thread(list_sessions, int(command.get('year',2024)))
                    if hasattr(self,'session_catalog'):
                        self.session_catalog[int(command.get('year',2024))]=sessions
                    await self.send(client, {'version':1,'type':'sessions','sessions':sessions})
                elif action == 'load':
                    await self.status('archive-loading')
                    clip = await asyncio.to_thread(fetch_clip, str(command['path']), float(command.get('start',0)), float(command.get('duration',120)))
                    await self.start_clip(clip)
                elif action == 'windows' and self.clip:
                    from .windows import recommend_windows
                    windows = await asyncio.to_thread(recommend_windows,self.clip)
                    await self.send(client,{'version':1,'type':'windows','windows':windows})
                elif action == 'play'  and self.state.mode == 'TEST' and self.clip:
                    if self.state.playback == 'ended':
                        selected_speed=self.state.speed
                        await self.start_clip(self.clip)
                        self.state.speed=selected_speed
                    self.timeline.control(time.monotonic(),running=True,speed=self.state.speed)
                    self.state.playback = 'playing'
                elif action == 'pause' and self.state.mode == 'TEST':
                    self.timeline.control(time.monotonic(),running=False)
                    self.state.playback = 'paused'
                elif action == 'speed' and self.state.mode == 'TEST':
                    speed = float(command['speed'])
                    if speed not in (1,2,5,10):
                        raise ValueError('Unsupported speed')
                    self.timeline.control(time.monotonic(),speed=speed)
                    self.state.speed = speed
                elif action == 'live':
                    await self.start_live()
                else:
                    raise ValueError('Unsupported action')
                await self.broadcast(self.transport_message('status', playbackInfo=self.playback_info()))
            except Exception:
                # Never send upstream exception text: auth libraries can include
                # response bodies, URLs or account details in their exceptions.
                self.error = 'Archive/control request failed. Check local authentication, topic availability and window limits. Existing mode/data retained.'
                await self.send(client, {'version':1,'type':'control-error','error':self.error})

    async def connection(self, websocket):
        self.clients.add(websocket)
        try:
            await self.send(websocket,self.snapshot())
            await self.send(websocket, {'version':1,'type':'controls','enabled':self.allow_test})
            async for text in websocket:
                try:
                    command = json.loads(text)
                    if isinstance(command,dict):
                        await self.command(websocket, command)
                except (ValueError, TypeError):
                    pass
        finally:
            self.clients.discard(websocket)

    async def run(self, args):
        self.configure_preparation(args.circuit_store, args.allow_prepare)
        from .controller_service import ControllerService
        forced='MANUAL' if getattr(args,'manual',False) else 'AUTO' if getattr(args,'auto',False) else None
        self.autonomy=ControllerService(self,self.asset_store.root/'controller.json',forced)
        async with serve(self.connection, '127.0.0.1', args.port, max_size=65536,
                         origins=['http://localhost:5173','http://127.0.0.1:5173','http://localhost:4173','http://127.0.0.1:4173',None]):
            print(f'Bridge: ws://127.0.0.1:{args.port}; TEST controls {"enabled" if self.allow_test else "disabled"}')
            heartbeat = asyncio.create_task(self.heartbeat())
            controller_task=asyncio.create_task(self.autonomy.run())
            try:
                if args.recording:
                    await self.start_clip(load_recording(args.recording))
                elif not args.idle and self.autonomy.machine.mode=='MANUAL':
                    await self.start_live()
                await asyncio.Future()
            finally:
                heartbeat.cancel()
                controller_task.cancel()
                await asyncio.gather(heartbeat,controller_task,return_exceptions=True)
                await self.autonomy.close()
                await self.stop_source()
                if self.recording_path and self.recording:
                    save_clip(self.recording_path,self.recording)
                    print('Bounded LiveF1 recording saved locally.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operating=parser.add_mutually_exclusive_group()
    operating.add_argument('--auto',action='store_true',help='Explicitly enable autonomous session control (default on first startup).')
    operating.add_argument('--manual',action='store_true',help='Developer override; never auto-switch LIVE/TEST.')
    parser.add_argument('--allow-prepare',action='store_true',help='Enable local, bounded circuit preparation jobs.')
    parser.add_argument('--circuit-store',help='Writable prepared circuit directory (default circuit-assets).')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--allow-test',action='store_true',help='Enable local historical-session controls (development only).')
    parser.add_argument('--idle',action='store_true',help='Start without connecting to the live feed.')
    parser.add_argument('--login',action='store_true',help='Authenticate locally using LiveF1; never paste credentials into ChatGPT.')
    parser.add_argument('--record',help='Save at most 120 seconds / 32 MiB of real live messages on exit.')
    parser.add_argument('--recording',help='Load a previously captured real LiveF1 clip as TEST.')
    args = parser.parse_args()
    # Upstream may log connection exceptions containing sensitive details. Keep
    # diagnostics in our own sanitized status channel; do not enable debug logs.
    logging.getLogger('livef1').disabled = True
    if args.login:
        from livef1 import login
        try:
            login()
        except Exception:
            print('Local LiveF1 sign-in failed. Check your credentials/entitlement locally; do not share them.')
            raise SystemExit(1) from None
    bridge = Bridge(args.allow_test, args.record)
    try:
        asyncio.run(bridge.run(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
