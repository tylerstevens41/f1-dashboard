import unittest
from unittest.mock import AsyncMock,patch
from datetime import datetime,timezone,timedelta
from bridge.server import Bridge


class ManualLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_controls_work_without_allow_test(self):
        bridge=Bridge(allow_test=False);bridge.start_live=AsyncMock()
        await bridge.command(None,{'action':'live'})
        bridge.start_live.assert_awaited_once_with(None)
        bridge.send=AsyncMock()
        await bridge.command(None,{'action':'load','path':'historical'})
        self.assertIn('disabled',bridge.send.call_args.args[1]['error'])

    async def test_discovery_filters_real_metadata_without_loading_archive(self):
        bridge=Bridge();bridge.send=AsyncMock();today=datetime.now(timezone.utc)
        session={'path':'published-only','start':today.isoformat(),'session':'Race','year':today.year,'label':'Published Race','circuit':{'Key':42,'ShortName':'Fixture'}}
        old={**session,'path':'old','start':(today-timedelta(days=30)).isoformat()}
        with patch('bridge.server.list_sessions',return_value=[session,old]),patch('bridge.server.fetch_clip',side_effect=AssertionError('no archive')):
            await bridge.command(None,{'action':'live-sessions'})
        self.assertEqual(bridge.send.call_args.args[1]['sessions'],[session])

    async def test_selected_live_identity_blocks_other_session_telemetry(self):
        bridge=Bridge();bridge.broadcast=AsyncMock()
        bridge.live_expected={'path':'current','circuit':{'Key':42},'session':'Race','start':'2026-11-08T12:00:00'};bridge.live_confirmed=False
        await bridge.emit('SessionInfo',{'Path':'older','Key':1})
        await bridge.emit('DriverList',{'1':{'Tla':'OLD'}})
        self.assertEqual(bridge.state.upstream,'waiting-session');self.assertNotIn('DriverList',bridge.state.topics)
        await bridge.emit('SessionInfo',{'Path':'current','Key':2})
        await bridge.emit('DriverList',{'1':{'Tla':'NEW'}})
        self.assertEqual(bridge.state.topics['DriverList']['1']['Tla'],'NEW')
        self.assertTrue(bridge.live_confirmed)

    async def test_stop_clears_live_state_and_does_not_stop_test(self):
        bridge=Bridge();bridge.broadcast=AsyncMock();bridge.stop_source=AsyncMock();bridge.send=AsyncMock()
        bridge.state.topics={'DriverList':{'1':{}}}
        await bridge.command(None,{'action':'live-stop'})
        self.assertEqual(bridge.state.upstream,'disconnected');self.assertEqual(bridge.state.topics,{})
        bridge.state.reset('TEST');bridge.stop_source.reset_mock()
        await bridge.command(None,{'action':'live-stop'})
        bridge.stop_source.assert_not_awaited()

    async def test_restart_and_reconnect_clear_test_and_require_identity_again(self):
        bridge=Bridge();bridge.broadcast=AsyncMock();bridge.run_live=AsyncMock()
        bridge.state.reset('TEST');bridge.clip={'old':True};bridge.timeline=object()
        expected={'path':'current'}
        await bridge.start_live(expected);await bridge.stop_source()
        self.assertEqual(bridge.state.mode,'LIVE');self.assertIsNone(bridge.clip);self.assertIsNone(bridge.timeline)
        bridge.live_confirmed=True
        await bridge.begin_live_snapshot();self.assertFalse(bridge.live_confirmed)

    async def test_live_snapshot_and_feed_dispatch_share_normalized_pipeline(self):
        from bridge.live import DashboardClient
        emit=AsyncMock();status=AsyncMock();snapshot=AsyncMock()
        client=DashboardClient(emit,status,snapshot)
        self.assertIn('Position.z',client.topics);self.assertIn('TimingData',client.topics)
        await client._dispatch({'type':3,'result':{'DriverList':{'1':{'Tla':'ABC'}}}})
        snapshot.assert_awaited_once();emit.assert_awaited_with('DriverList',{'1':{'Tla':'ABC'}},None)
        await client._dispatch({'target':'feed','arguments':['SessionStatus',{'Status':'Finished'},'2026-11-08T20:00:00Z']})
        emit.assert_awaited_with('SessionStatus',{'Status':'Finished'},'2026-11-08T20:00:00Z')

    async def test_live_circuit_lookup_uses_actual_metadata_and_never_prepares_geometry(self):
        from types import SimpleNamespace
        from pathlib import Path
        import tempfile
        bridge=Bridge();bridge.send=AsyncMock();bridge.preparation_tasks={};bridge.allow_prepare=False
        # 42 is a synthetic test identity, never a guessed Brazilian circuit key.
        bridge.state.topics={'SessionInfo':{'Meeting':{'Circuit':{'Key':42,'ShortName':'Sao Paulo'}}}}
        meta=dict(id='fixture-brazil',assetKey='circuit-42-2026',path='published-race',year=2026,event='Synthetic Sao Paulo',session='Race',circuitKey='42',name='Sao Paulo')
        value={'identity':meta,'complete':True}
        with tempfile.TemporaryDirectory() as temp:
            bridge.asset_store=SimpleNamespace(lookup=__import__('unittest.mock',fromlist=['Mock']).Mock(return_value=value),directory=lambda _:Path(temp))
            with patch('bridge.preparation.prepare',side_effect=AssertionError('no regeneration')):
                await bridge.command(None,{'action':'circuit-lookup','year':2026})
            bridge.asset_store.lookup.assert_called_once_with(2026,None,'42')
        self.assertEqual(bridge.send.call_args_list[0].args[1]['type'],'circuit-assets')

    async def test_live_gps_diagnostics_count_identity_drops_without_exposing_payload(self):
        bridge=Bridge();bridge.broadcast=AsyncMock()
        bridge.live_expected={'path':'current'};bridge.live_confirmed=False
        await bridge.emit('Position.z',{'PRIVATE_PROVIDER_DATA':'not exported'})
        self.assertEqual(bridge.gps_diagnostics['rawMessages'],1)
        self.assertEqual(bridge.gps_diagnostics['identityDrops'],1)
        self.assertIsNotNone(bridge.gps_diagnostics['rawReceivedUtcMs'])
        self.assertNotIn('PRIVATE',str(bridge.transport_message('status')))
        await bridge.begin_live_snapshot()
        self.assertEqual(bridge.gps_diagnostics['subscriptionSnapshots'],1)
