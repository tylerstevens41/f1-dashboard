"""WebSocket integration with explicitly synthetic protocol fixtures; no feed claims."""
import asyncio
import json
import time
import unittest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from bridge.server import Bridge


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_reconnect_and_test_same_topic_pipeline(self):
        bridge = Bridge(allow_test=True)
        async with serve(bridge.connection,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}') as client:
                self.assertEqual(json.loads(await client.recv())['type'],'snapshot')
                self.assertEqual(json.loads(await client.recv())['type'],'controls')
                await bridge.emit('DriverList',{'1':{'Tla':'UNIT'}})
                update=json.loads(await client.recv())
                self.assertEqual(update['data']['1']['Tla'],'UNIT')
            async with connect(f'ws://127.0.0.1:{port}') as client:
                snapshot=json.loads(await client.recv())
                self.assertEqual(snapshot['topics']['DriverList']['1']['Tla'],'UNIT')
                await client.recv()
                clip={'source':'LiveF1','format':'livef1-clip-v1','originMs':1000,'durationMs':100,
                      'sessionPath':'unit-fixture','initial':{},'events':[{'offsetMs':0,'topic':'SessionInfo','payload':{'Key':2}},
                          {'offsetMs':0,'topic':'DriverList','payload':{'4':{'Tla':'TEST'}}}]}
                await bridge.start_clip(clip)
                bridge.timeline.control(time.monotonic(),running=True)
                bridge.state.playback='playing'
                await asyncio.sleep(0.15)
                self.assertEqual(bridge.state.topics['DriverList']['4']['Tla'],'TEST')
                self.assertNotIn('1',bridge.state.topics['DriverList'])
                self.assertEqual(bridge.state.playback,'ended')
                self.assertEqual(bridge.state.mode,'TEST')
                await bridge.stop_source()

    async def test_test_clock_and_pause_are_broadcast_to_every_viewer(self):
        bridge=Bridge(allow_test=True)
        async with serve(bridge.connection,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}') as a,connect(f'ws://127.0.0.1:{port}') as b:
                for client in (a,b):
                    await client.recv();await client.recv()
                await bridge.start_clip({'originMs':1000,'durationMs':1000,'initial':{},'events':[]})
                await a.recv();await b.recv()
                await a.send(json.dumps({'action':'play'}))
                async def until(client,kind,playback=None):
                    while True:
                        message=json.loads(await asyncio.wait_for(client.recv(),1))
                        if message['type']==kind and (playback is None or message.get('playback')==playback):return message
                clock=await until(b,'clock')
                self.assertGreaterEqual(clock['clockMs'],1000)
                await a.send(json.dumps({'action':'pause'}))
                paused=await until(b,'status','paused')
                self.assertEqual(paused['mode'],'TEST')
                with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(b.recv(),0.08)
                await bridge.stop_source()

    async def test_delayed_event_delivery_does_not_drop_clip_tail(self):
        bridge=Bridge(allow_test=True)
        received=[]
        async def broadcast(message):
            if message['type']=='topic':
                received.append(message['data'])
                await asyncio.sleep(0.09)
        bridge.broadcast=broadcast
        clip={'originMs':1000,'durationMs':100,'initial':{},'events':[
            {'offsetMs':25,'topic':'SessionStatus','payload':{'Status':'Started'}},
            {'offsetMs':95,'topic':'SessionStatus','payload':{'Status':'Finished'}}]}
        await bridge.start_clip(clip)
        bridge.timeline.control(time.monotonic(),running=True)
        bridge.state.playback='playing'
        await asyncio.wait_for(bridge.source_task,1)
        self.assertEqual([record['Status'] for record in received],['Started','Finished'])
        self.assertEqual(bridge.state.playback,'ended')
        await bridge.stop_source()

    async def test_production_bridge_rejects_test_controls(self):
        bridge=Bridge()
        sent=[]
        async def send(client,message):sent.append(message)
        bridge.send=send
        await bridge.command(None,{'action':'load','path':'anything'})
        self.assertEqual(sent[-1]['type'],'control-error')
        self.assertEqual(bridge.state.mode,'LIVE')

    async def test_pause_keeps_virtual_clock_still(self):
        bridge=Bridge(True)
        await bridge.start_clip({'originMs':1000,'durationMs':1000,'initial':{},'events':[]})
        await asyncio.sleep(0.08)
        self.assertEqual(bridge.state.clock_ms,1000)
        self.assertEqual(bridge.offset,0)
        await bridge.stop_source()


if __name__=='__main__':unittest.main()
