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
from .protocol import TOPICS, RaceState


class Bridge:
    def __init__(self, allow_test=False, recording=None):
        self.state = RaceState()
        self.clients = set()
        self.source_task = None
        self.control_lock = asyncio.Lock()
        self.allow_test = allow_test
        self.error = None
        self.recording_path = recording
        self.recording = None
        self.record_started = None
        self.clip = None
        self.offset = 0
        self.last_tick = time.monotonic()

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

    def snapshot(self):
        return {**self.state.snapshot(),'playbackInfo':self.playback_info()}

    async def status(self, status):
        self.state.upstream = status
        await self.broadcast(self.state.envelope('status', error=self.error, playbackInfo=self.playback_info()))

    async def emit(self, topic, payload, timestamp=None, clock_ms=None):
        if topic not in TOPICS:
            return
        if self.recording_path and self.state.mode == 'LIVE':
            self.capture(topic, payload)
        try:
            messages = self.state.ingest(topic, payload, timestamp, clock_ms)
        except (ValueError, KeyError, TypeError):
            self.error = f'Invalid {topic} update; retained previous state.'
            await self.broadcast(self.state.envelope('status', error=self.error, playbackInfo=self.playback_info()))
            return
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

    async def start_live(self):
        await self.stop_source()
        self.clip = None
        self.state.reset('LIVE')
        self.error = None
        await self.broadcast(self.snapshot())
        self.source_task = asyncio.create_task(self.run_live())

    async def begin_live_snapshot(self):
        self.state.reset('LIVE')
        self.state.upstream = 'connected'
        await self.broadcast(self.snapshot())

    async def run_live(self):
        try:
            from .live import DashboardClient
            client = DashboardClient(self.emit, self.status, self.begin_live_snapshot)
            await client._run()  # pinned LiveF1 1.3.0 transport; see docs
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = 'LiveF1 connection failed. Verify backend login locally; no credentials are sent to the browser.'
            await self.status('error')

    async def start_clip(self, clip):
        await self.stop_source()
        self.clip = clip
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
                self.offset = min(self.clip['durationMs'], self.offset + (now-self.last_tick)*1000*self.state.speed)
                self.state.clock_ms = self.clip['originMs'] + self.offset
                while index < len(self.clip['events']) and self.clip['events'][index]['offsetMs'] <= self.offset:
                    event = self.clip['events'][index]
                    await self.emit(event['topic'], event['payload'], clock_ms=self.clip['originMs']+event['offsetMs'])
                    index += 1
                self.state.clock_ms = self.clip['originMs'] + self.offset
            self.last_tick = now
            if self.state.playback == 'playing':
                await self.broadcast(self.state.envelope('clock',playbackInfo=self.playback_info()))
            await asyncio.sleep(0.025)
        self.state.playback = 'ended'
        await self.broadcast(self.state.envelope('status', playbackInfo=self.playback_info()))

    async def heartbeat(self):
        while True:
            if self.state.mode == 'LIVE':
                self.state.clock_ms = datetime.now(timezone.utc).timestamp()*1000
            await self.broadcast(self.state.envelope('status', error=self.error, playbackInfo=self.playback_info()))
            await asyncio.sleep(1)

    async def command(self, client, command):
        if not self.allow_test:
            await self.send(client, {'version':1,'type':'control-error','error':'TEST controls are disabled on this bridge.'})
            return
        async with self.control_lock:
            try:
                action = command.get('action')
                if action == 'sessions':
                    sessions = await asyncio.to_thread(list_sessions, int(command.get('year',2024)))
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
                        await self.start_clip(self.clip)
                    self.state.playback = 'playing'
                    self.last_tick = time.monotonic()
                elif action == 'pause' and self.state.mode == 'TEST':
                    self.state.playback = 'paused'
                elif action == 'speed' and self.state.mode == 'TEST':
                    speed = float(command['speed'])
                    if speed not in (1,2,5,10):
                        raise ValueError('Unsupported speed')
                    self.state.speed = speed
                elif action == 'live':
                    await self.start_live()
                else:
                    raise ValueError('Unsupported action')
                await self.broadcast(self.state.envelope('status', playbackInfo=self.playback_info()))
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
        async with serve(self.connection, '127.0.0.1', args.port, max_size=65536,
                         origins=['http://localhost:5173','http://127.0.0.1:5173','http://localhost:4173','http://127.0.0.1:4173',None]):
            print(f'Bridge: ws://127.0.0.1:{args.port}; TEST controls {"enabled" if self.allow_test else "disabled"}')
            heartbeat = asyncio.create_task(self.heartbeat())
            try:
                if args.recording:
                    await self.start_clip(load_recording(args.recording))
                elif not args.idle:
                    await self.start_live()
                await asyncio.Future()
            finally:
                heartbeat.cancel()
                await self.stop_source()
                if self.recording_path and self.recording:
                    save_clip(self.recording_path,self.recording)
                    print('Bounded LiveF1 recording saved locally.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
