"""Deterministic control-plane fixtures; not real LIVE telemetry validation."""
from datetime import datetime,timezone
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch
import asyncio
from bridge.autonomous import SessionController,utc_start,identity_matches,combine_schedule
from bridge.controller_service import ControllerService
from bridge.server import Bridge

BASE=1800000000

def session(kind='Race',offset=0,path=None):
    return {'path':path or 'SIMULATION/'+kind,'start':datetime.fromtimestamp(BASE+offset,timezone.utc).isoformat(),
            'session':kind,'year':2027,'location':'Synthetic venue','circuit':{'Key':42,'ShortName':'Fixture'}}


def observation(s,**extra):
    return {'session':{'Path':s['path'],'Name':s['session'],'Meeting':{'Circuit':s['circuit']}},'status':'Started','sourceRunning':True,'freshGps':True,**extra}


class ControllerTests(TestCase):
    def test_advisory_not_active_and_late_publication_can_connect(self):
        c=SessionController();s=session();advice={**s,'path':None,'advisoryId':'unit'}
        self.assertIsNone(c.tick(BASE-4000,[advice],{}));self.assertEqual(c.state,'DASHBOARD')
        c.tick(BASE-2000,[advice],{});self.assertEqual(c.state,'SESSION_APPROACHING')
        self.assertIsNone(c.tick(BASE-300,[advice],{}));self.assertEqual(c.state,'WAITING_FOR_SESSION')
        s['advisoryId']='unit';self.assertEqual(c.tick(BASE+100,[s],{}),'connect')
        c.tick(BASE+102,[s],observation(s,status='Inactive'));self.assertNotEqual(c.state,'LIVE')
        c.tick(BASE+110,[s],observation(s));self.assertEqual(c.state,'LIVE')

    def test_practice_qualifying_race_sequence_and_confirmed_completion(self):
        c=SessionController();sessions=[session('Practice 1'),session('Qualifying',7200),session('Race',14400)]
        for i,s in enumerate(sessions):
            t=BASE+i*7200
            self.assertEqual(c.tick(t,sessions,{}),'connect')
            c.tick(t+2,sessions,observation(s));self.assertEqual(c.state,'LIVE');self.assertEqual(c.snapshot()['view'],'live')
            c.tick(t+100,sessions,observation(s,status='Finished',freshGps=False))
            self.assertNotEqual(c.state,'SESSION_COMPLETED')
            c.tick(t+112,sessions,observation(s,status='Finished',freshGps=False));self.assertEqual(c.state,'SESSION_COMPLETED')
            self.assertEqual(c.tick(t+140,sessions,{}),'stop');self.assertEqual(c.state,'DASHBOARD')
        self.assertEqual(len(c.completed),3)

    def test_sprint_sessions_aliases_and_duplicate_metadata(self):
        s=session('Sprint Qualifying');advice={**s,'path':None,'advisoryId':'SQ'}
        data=combine_schedule([{**s,'session':'Sprint Shootout'},s],[advice])
        self.assertEqual(len(data),1)
        for kind in ('Practice 1','Sprint Qualifying','Sprint','Qualifying','Race'):
            c=SessionController();s=session(kind);c.tick(BASE,[s],{});c.tick(BASE+2,[s],observation(s));self.assertEqual(c.state,'LIVE')

    def test_red_flag_never_finishes_until_explicit_finalised(self):
        c=SessionController();s=session();c.tick(BASE,[s],{});c.tick(BASE+2,[s],observation(s))
        c.tick(BASE+5,[s],observation(s,status='Aborted',trackStatus='5',freshGps=False));self.assertEqual(c.state,'SESSION_SUSPENDED')
        c.tick(BASE+100,[s],observation(s,status='Finished',trackStatus='5',freshGps=False));self.assertEqual(c.state,'SESSION_SUSPENDED')
        c.tick(BASE+105,[s],observation(s,status='Started'));self.assertEqual(c.state,'LIVE')
        c.tick(BASE+200,[s],observation(s,status='Finalised',trackStatus='5'))
        c.tick(BASE+211,[s],observation(s,status='Finalised',trackStatus='5'));self.assertEqual(c.state,'SESSION_COMPLETED')

    def test_outage_retains_view_and_recovers_without_duplicate_subscriptions(self):
        c=SessionController();s=session();c.tick(BASE,[s],{});c.tick(BASE+2,[s],observation(s))
        c.tick(BASE+10,[s],observation(s,freshGps=False));self.assertEqual(c.state,'LIVE_STALE')
        c.tick(BASE+20,[s],observation(s,freshGps=False,sourceRunning=False,upstream='disconnected'));self.assertEqual(c.state,'RECOVERING');self.assertEqual(c.snapshot()['view'],'live')
        self.assertIsNone(c.tick(BASE+20.1,[s],observation(s,freshGps=False,sourceRunning=False)))
        c.tick(BASE+30,[s],observation(s));self.assertEqual(c.state,'LIVE')
        self.assertIsNone(c.tick(BASE+31,[s],observation(s)))

    def test_no_fixed_end_time_and_identity_mismatch_never_promotes_live(self):
        c=SessionController();s=session();c.tick(BASE,[s],{})
        c.tick(BASE+2,[s],observation(session(path='SIMULATION/WRONG')));self.assertNotEqual(c.state,'LIVE')
        c.tick(BASE+3,[s],observation(s));c.tick(BASE+99999,[s],observation(s,freshGps=False));self.assertIn(c.state,('LIVE_STALE','RECOVERING'));self.assertEqual(c.snapshot()['view'],'live')
        self.assertNotIn(s['path'],c.completed)
        self.assertFalse(identity_matches(s,{'Path':s['path'],'Meeting':{'Circuit':{'Key':999}}}))

    def test_manual_and_test_override_are_authoritative_and_persist(self):
        c=SessionController();s=session();c.tick(BASE,[s],{})
        c.set_mode('MANUAL',BASE+1);self.assertIsNone(c.tick(BASE+2,[s],observation(s)))
        restored=SessionController(c.checkpoint());self.assertEqual(restored.mode,'MANUAL')
        c.set_mode('AUTO',BASE+3);c.tick(BASE+4,[s],{'dataMode':'TEST'});self.assertEqual(c.mode,'MANUAL')

    def test_completed_sessions_survive_restart_but_live_approval_does_not(self):
        c=SessionController();s=session();c.tick(BASE,[s],{});c.tick(BASE+2,[s],observation(s))
        restored=SessionController(c.checkpoint());self.assertEqual(restored.state,'DASHBOARD');self.assertIsNone(restored.last_live)
        c.tick(BASE+10,[s],observation(s,status='Finished'));c.tick(BASE+21,[s],observation(s,status='Finished'))
        restored=SessionController(c.checkpoint());self.assertIsNone(restored.tick(BASE+40,[s],{}));self.assertEqual(restored.state,'DASHBOARD')

    def test_timezone_and_schedule_day_difference_do_not_invent_identity(self):
        self.assertIsNone(utc_start({'start':'2026-11-21T23:00:00'}))
        self.assertEqual(utc_start({'start':'2026-03-29T14:00:00','gmtOffset':'09:00:00'}),utc_start({'start':'2026-03-29T05:00:00Z'}))
        self.assertEqual(utc_start({'start':'2026-11-08T14:00:00','gmtOffset':'-03:00:00'}),utc_start({'start':'2026-11-08T17:00:00Z'}))
        published={**session(),'start':'2026-11-21T23:00:00','gmtOffset':'-08:00'}
        advice={**session(),'path':None,'start':'2026-11-22T07:00:00Z','advisoryId':'timezone'}
        data=combine_schedule([published],[advice]);self.assertEqual(len(data),1);self.assertEqual(data[0]['path'],published['path'])
        self.assertEqual(data[0]['advisoryId'],'timezone')

    def test_retry_budget_has_cooldown_and_running_source_is_not_restarted(self):
        c=SessionController();s=session();now=BASE
        for i in range(8):
            self.assertEqual(c.tick(now,[s],{'sourceRunning':False}),'connect');now=c.retry_at
        self.assertEqual(c.retry_at-(now-300),300)
        self.assertIsNone(c.tick(now-1,[s],{'sourceRunning':False}))
        self.assertIsNone(c.tick(now,[s],observation(s)))

    def test_new_actual_published_session_revalidates_source_identity(self):
        c=SessionController();first=session('Practice 1');second=session('Practice 2',1800)
        c.tick(BASE,[first,second],{});c.tick(BASE+2,[first,second],observation(first))
        result=c.tick(BASE+1800,[first,second],observation(second,expectedPath=first['path']))
        self.assertEqual(c.selected['path'],second['path']);self.assertEqual(result,'connect')


class ServiceTests(IsolatedAsyncioTestCase):
    async def test_manual_bridge_commands_take_ownership_without_autonomous_subscription(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge=Bridge();bridge.broadcast=AsyncMock();bridge.start_live=AsyncMock()
            service=ControllerService(bridge,Path(temp)/'controller.json');bridge.autonomy=service
            await bridge.command(None,{'action':'live'})
            self.assertEqual(service.machine.mode,'MANUAL');bridge.start_live.assert_awaited_once()
            restored=ControllerService(bridge,Path(temp)/'controller.json');self.assertEqual(restored.machine.mode,'MANUAL')
            bridge.state.reset('TEST');bridge.send=AsyncMock()
            await bridge.command(None,{'action':'controller-mode','mode':'AUTO'})
            self.assertEqual(service.machine.mode,'MANUAL');self.assertEqual(bridge.state.mode,'TEST')
            await service.close()

    async def test_missing_assets_reported_and_lookup_does_not_repeat_geometry_broadcast(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge=Bridge();bridge.broadcast=AsyncMock();bridge.start_live=AsyncMock()
            bridge.asset_store=SimpleNamespace(lookup=Mock(return_value=None))
            service=ControllerService(bridge,Path(temp)/'controller.json');bridge.autonomy=service
            s=session();service.sessions=[s];service.discovery_due=BASE+1000
            bridge.source_task=SimpleNamespace(done=lambda:False);bridge.live_expected=s
            bridge.state.topics={'SessionInfo':{**observation(s)['session'],'StartDate':s['start']},'SessionStatus':{'Status':'Started'},'Position.z':{'1':{'X':10,'Y':20,'_sampleTimeMs':BASE*1000}}}
            await service.tick(BASE);self.assertEqual(service.machine.state,'LIVE')
            self.assertIn('missing',service.machine.circuit);bridge.start_live.assert_not_awaited()
            await service.tick(BASE+2);self.assertEqual(bridge.asset_store.lookup.call_count,1)
            await service.close()

    async def test_slow_discovery_does_not_block_live_controller_or_manual_override(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge=Bridge();service=ControllerService(bridge,Path(temp)/'controller.json');bridge.autonomy=service
            gate=asyncio.Event()
            async def discover(_):await gate.wait()
            service.discover=discover
            await asyncio.wait_for(service.tick(BASE),.2)
            service.mode('MANUAL');await service.close()
            self.assertEqual(service.machine.mode,'MANUAL')

class SimulationTests(TestCase):
    def test_complete_weekend_simulation_is_isolated_and_deterministic(self):
        import io,json
        from contextlib import redirect_stdout
        from bridge.autonomous import simulate
        out=io.StringIO()
        with redirect_stdout(out):simulate()
        rows=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(rows),36)
        self.assertTrue(all(row['simulation'] for row in rows))
        self.assertEqual({r['session'] for r in rows},{'Practice 1','Qualifying','Race'})
        self.assertTrue({'DASHBOARD','SESSION_APPROACHING','WAITING_FOR_SESSION','CONNECTING','LIVE','RECOVERING','SESSION_SUSPENDED','SESSION_COMPLETED'}<={r['state'] for r in rows})
        self.assertEqual(rows[-1]['state'],'DASHBOARD')

class TelemetryEvidenceTests(IsolatedAsyncioTestCase):
    async def test_snapshot_clock_does_not_masquerade_as_live_delta(self):
        bridge=Bridge();bridge.broadcast=AsyncMock()
        await bridge.emit('TimingData',{'Lines':{'1':{'Position':'1'}}})
        self.assertIsNone(bridge.last_live_delta)
        await bridge.note_live_activity('TimingData')
        await bridge.emit('TimingData',{'Lines':{'1':{'Position':'2'}}})
        self.assertIsNotNone(bridge.last_live_delta)
        await bridge.begin_live_snapshot();self.assertIsNone(bridge.last_live_delta)

class AssetStabilityTests(IsolatedAsyncioTestCase):
    async def test_unchanged_prepared_asset_is_not_rebroadcast_each_poll(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge=Bridge();bridge.broadcast=AsyncMock()
            asset={'geometryId':'synthetic-fixture','corners':{'fixture':True},'sectors':{'fixture':True}}
            bridge.asset_store=SimpleNamespace(lookup=Mock(return_value=asset))
            service=ControllerService(bridge,Path(temp)/'controller.json');bridge.autonomy=service
            s=session();service.sessions=[s];service.discovery_due=BASE+1000
            bridge.source_task=SimpleNamespace(done=lambda:False);bridge.live_expected=s
            bridge.state.topics={'SessionInfo':{**observation(s)['session'],'StartDate':s['start']},'SessionStatus':{'Status':'Started'},'Position.z':{'1':{'X':10,'Y':20,'_sampleTimeMs':BASE*1000}}}
            await service.tick(BASE)
            bridge.state.topics['Position.z']['1']['_sampleTimeMs']=(BASE+61)*1000
            await service.tick(BASE+61)
            self.assertEqual(bridge.asset_store.lookup.call_count,2)
            assets=[c for c in bridge.broadcast.call_args_list if c.args[0]['type']=='circuit-assets']
            self.assertEqual(len(assets),1)
            await service.close()

class RefreshTests(TestCase):
    def test_unconfirmed_identity_refresh_is_bounded_not_per_tick(self):
        c=SessionController();s=session();c.tick(BASE,[s],{})
        self.assertIsNone(c.tick(BASE+20,[s],{'sourceRunning':True,'expectedPath':s['path']}))
        self.assertEqual(c.tick(BASE+65,[s],{'sourceRunning':True,'expectedPath':s['path']}),'connect')
        self.assertIsNone(c.tick(BASE+66,[s],{'sourceRunning':True,'expectedPath':s['path']}))

class MetadataPersistenceTests(IsolatedAsyncioTestCase):
    async def test_restart_can_monitor_cached_metadata_but_never_restores_live_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge=Bridge();path=Path(temp)/'controller.json'
            service=ControllerService(bridge,path);service.sessions=[session()];service.last_discovery=BASE
            service.machine.tick(BASE,[session()],{});service.machine.tick(BASE+2,[session()],observation(session()))
            service.persist()
            restored=ControllerService(bridge,path)
            self.assertEqual(restored.sessions[0]['path'],session()['path']);self.assertEqual(restored.last_discovery,BASE)
            self.assertEqual(restored.machine.state,'DASHBOARD');self.assertIsNone(restored.machine.last_live)
            await service.close();await restored.close()
