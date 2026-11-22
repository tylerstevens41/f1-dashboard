"""Supplied Vegas path, but invented keys/GPS; no recorded race data or LIVE proof."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch

from bridge.live_reconciliation import reconcile,published_session_info
from bridge.autonomous import SessionController
from bridge.controller_service import ControllerService
from bridge.server import Bridge
from bridge.archive import ArchiveUnavailable

NOW=datetime(2026,11,22,4,15,tzinfo=timezone.utc).timestamp()
VEGAS_PATH='2026/2026-11-21_Las_Vegas_Grand_Prix/2026-11-21_Race/'

def info():
    return {'Path':VEGAS_PATH,'Key':99901,'Name':'Race','StartDate':'2026-11-21T20:00:00',
            'GmtOffset':'-08:00:00','Meeting':{'Key':99902,'Name':'Las Vegas Grand Prix',
            'Location':'Las Vegas','Circuit':{'Key':99903,'ShortName':'Las Vegas'}}}

def advice():
    return {'path':None,'year':2026,'start':'2026-11-22T04:00:00Z','session':'Race',
            'event':'Las Vegas Grand Prix','location':'Las Vegas','advisoryId':'fixture:Race'}

def observation():
    return {'session':info(),'dataMode':'LIVE','identityConfirmed':True,'upstream':'connected',
            'status':'Started','sourceRunning':True,'freshGps':True,'freshDelta':True,'expectedPath':None}

def confirmation():return {'path':VEGAS_PATH,'sessionInfo':info()}


class ReconciliationTests(TestCase):
    def test_flags_and_countdown_never_replace_independent_provider_metadata(self):
        result,check=reconcile(NOW,advice(),observation())
        self.assertIsNone(result);self.assertEqual(check['status'],'provider-confirmation-required')
        result,check=reconcile(NOW,advice(),observation(),confirmation())
        self.assertEqual(result['path'],VEGAS_PATH);self.assertEqual(result['year'],2026)
        self.assertEqual(result['circuit']['Key'],99903)
        self.assertEqual(check['status'],'verified-current-provider-session')

    def test_missing_or_conflicting_feed_identity_is_blocked(self):
        cases=[]
        for key in ('Key','Name','StartDate','GmtOffset','Path'):
            value=observation();del value['session'][key];cases.append(value)
        for key in ('Key','Circuit'):
            value=observation();del value['session']['Meeting'][key];cases.append(value)
        for field,replacement in [('Path',VEGAS_PATH.replace('2026/','2025/',1)),('Name','Qualifying'),('Type','Practice'),('StartDate','2026-11-20T20:00:00')]:
            value=observation();value['session'][field]=replacement;cases.append(value)
        value=observation();value['session']['Meeting']['Circuit']['Key']=0;cases.append(value)
        for field,replacement in [('dataMode','TEST'),('identityConfirmed',False),('sourceRunning',False),('upstream','waiting-session'),('status','Finished'),('expectedPath','2026/other/Race/')]:
            value=observation();value[field]=replacement;cases.append(value)
        value=observation();value.update(freshGps=False,freshDelta=False);cases.append(value)
        for value in cases:
            with self.subTest(value=value):self.assertIsNone(reconcile(NOW,advice(),value,confirmation())[0])

    def test_independent_metadata_conflicts_and_missing_fields_are_blocked(self):
        cases=[]
        for key in ('Key','Name','StartDate','GmtOffset','Meeting'):
            value=confirmation();del value['sessionInfo'][key];cases.append(value)
        for key,new in [('Key',99909),('Name','Qualifying'),('StartDate','2026-11-21T20:10:00'),('Path','2026/conflicting/Race/')]:
            value=confirmation();value['sessionInfo'][key]=new;cases.append(value)
        value=confirmation();value['sessionInfo']['Meeting']['Circuit']['Key']=99909;cases.append(value)
        value=confirmation();value['sessionInfo']['Meeting']['Key']=99909;cases.append(value)
        value=confirmation();value['path']='2026/other/Race/';cases.append(value)
        for value in cases:self.assertIsNone(reconcile(NOW,advice(),observation(),value)[0])
        value=confirmation();del value['sessionInfo']['Path']
        self.assertIsNotNone(reconcile(NOW,advice(),observation(),value)[0]) # Request path anchors published document.

    def test_catalog_conflicts_advisory_conflicts_and_ambiguity_fail_closed(self):
        base={'path':VEGAS_PATH,'year':2026,'session':'Race','circuit':{'Key':99903},'meetingKey':99902}
        for patch_data in ({'year':2025},{'session':'Qualifying'},{'event':'Other Grand Prix'},{'sessionKey':99909},{'circuit':{'Key':99909}},{'meetingKey':99909},{'start':'2026-11-22T04:30:00Z'}):
            self.assertIsNone(reconcile(NOW,advice(),observation(),confirmation(),[{**base,**patch_data}])[0])
        other={**advice(),'path':VEGAS_PATH.replace('Race/','Another_Race/')}
        self.assertIsNone(reconcile(NOW,advice(),observation(),confirmation(),[other])[0])
        for patch_data in ({'year':2025},{'event':'Other Grand Prix'},{'circuit':{'Key':99909}},{'meetingKey':99909}):
            self.assertIsNone(reconcile(NOW,{**advice(),**patch_data},observation(),confirmation())[0])

    def test_provider_aware_utc_and_local_date_align_but_unknown_timezone_does_not(self):
        value=observation();value['session']['StartDate']='2026-11-22T04:00:00Z'
        self.assertIsNotNone(reconcile(NOW,advice(),value,confirmation())[0])
        value['session']['GmtOffset']='-07:00:00'
        self.assertIsNone(reconcile(NOW,advice(),value,confirmation())[0])

    def test_fetch_uses_published_stream_merges_deltas_and_stays_bounded(self):
        initial=info();initial.pop('Path')
        records=['00:00:00.000'+json.dumps(initial),'00:00:01.000'+json.dumps({'Meeting':{'Location':'Las Vegas'}})]
        with patch('bridge.archive.small_json',return_value={'Feeds':{'SessionInfo':{'StreamPath':'actual-metadata.jsonStream'}}}),patch('bridge.archive.lines',return_value=iter(records)) as read:
            result=published_session_info(VEGAS_PATH)
            self.assertEqual(result['sessionInfo']['Key'],99901)
            self.assertEqual(read.call_args.args[0],VEGAS_PATH+'actual-metadata.jsonStream')
            self.assertEqual(read.call_args.kwargs['limit'],1024*1024)
        with patch('bridge.archive.small_json',return_value={'Feeds':{'SessionInfo':{'StreamPath':'../other.jsonStream'}}}):
            with self.assertRaises(ArchiveUnavailable):published_session_info(VEGAS_PATH)


class ReconciliationServiceTests(IsolatedAsyncioTestCase):
    def setup_bridge(self,temp):
        bridge=Bridge();bridge.broadcast=AsyncMock();bridge.start_live=AsyncMock();bridge.stop_source=AsyncMock()
        bridge.asset_store=SimpleNamespace(lookup=Mock(return_value={'geometryId':'synthetic','corners':None,'sectors':None}))
        bridge.source_task=SimpleNamespace(done=lambda:False)
        bridge.state.upstream='connected';bridge.last_live_delta=NOW
        bridge.state.topics={'SessionInfo':info(),'SessionStatus':{'Status':'Started'},
                             'Position.z':{'1':{'X':100,'Y':200,'_sampleTimeMs':NOW*1000}}}
        service=ControllerService(bridge,Path(temp)/'controller.json',force_mode='AUTO');bridge.autonomy=service
        service.sessions=[advice()];service.discovery_due=NOW+3600
        service.machine.tick(NOW-10,[advice()],{})
        return bridge,service

    async def test_supplied_diagnostics_adopt_existing_live_and_publish_wall_state(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info',return_value=confirmation()) as fetch:
            bridge,service=self.setup_bridge(temp)
            self.assertEqual(service.machine.selected['path'],None)
            await service.tick(NOW)
            await service.identity_task
            await service.tick(NOW+1)
            self.assertEqual(service.machine.state,'LIVE');self.assertEqual(service.snapshot()['view'],'live')
            self.assertEqual(bridge.live_expected['path'],VEGAS_PATH)
            bridge.start_live.assert_not_awaited();bridge.stop_source.assert_not_awaited();fetch.assert_called_once()
            state=bridge.snapshot()['controller'];self.assertEqual(state['reconciliation']['status'],'verified-current-provider-session')
            self.assertEqual(state['catalogDiagnostics']['feedPathEntries'],0)
            self.assertEqual(state['providerIdentityCheck']['state'],'received')
            self.assertTrue(any(c.args[0].get('controller',{}).get('view')=='live' for c in bridge.broadcast.call_args_list))
            # Once verified, real completion uses the existing confirmation/dwell.
            bridge.state.topics['SessionStatus']['Status']='Finished'
            await service.tick(NOW+3);self.assertNotEqual(service.machine.state,'SESSION_COMPLETED')
            await service.tick(NOW+15);self.assertEqual(service.machine.state,'SESSION_COMPLETED')
            await service.tick(NOW+36);self.assertEqual(service.snapshot()['view'],'dashboard')
            await service.close()

    async def test_stale_manual_and_test_never_fetch_or_promote(self):
        for mode in ('stale','MANUAL','TEST'):
            with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info') as fetch:
                bridge,service=self.setup_bridge(temp)
                if mode=='stale':bridge.last_live_delta=NOW-100;bridge.state.topics['Position.z']['1']['_sampleTimeMs']=(NOW-100)*1000
                elif mode=='MANUAL':service.mode('MANUAL')
                else:bridge.state.reset('TEST')
                await service.tick(NOW);self.assertIsNone(service.identity_task);fetch.assert_not_called()
                self.assertNotEqual(service.machine.state,'LIVE');bridge.start_live.assert_not_awaited()
                await service.close()

    async def test_auth_failure_has_backoff_and_safe_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info',side_effect=ArchiveUnavailable('PRIVATE TOKEN',code='authentication-required')) as fetch:
            bridge,service=self.setup_bridge(temp)
            await service.tick(NOW);await service.identity_task
            await service.tick(NOW+1)
            self.assertNotEqual(service.machine.state,'LIVE');fetch.assert_called_once()
            self.assertGreater(service.identity_due,NOW+1);self.assertNotIn('PRIVATE TOKEN',str(service.snapshot()))
            await service.close()

    async def test_catalog_start_without_timezone_is_diagnosed_and_independently_resolved(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info',return_value=confirmation()):
            bridge,service=self.setup_bridge(temp)
            service.published=[{'path':VEGAS_PATH,'year':2026,'start':'2026-11-21T20:00:00','session':'Race','circuit':{'Key':99903}}]
            await service.tick(NOW);await service.identity_task;await service.tick(NOW+1)
            self.assertEqual(service.machine.state,'LIVE')
            report=service.snapshot()['catalogDiagnostics'];self.assertEqual(report['feedPathEntries'],1);self.assertEqual(report['feedPathEntriesWithUsableStart'],0)
            await service.close()

    async def test_pending_metadata_does_not_block_manual_override(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge,service=self.setup_bridge(temp);gate=asyncio.Event()
            async def pending(*_):await gate.wait()
            service.confirm_provider_identity=pending
            await asyncio.wait_for(service.tick(NOW),.2)
            service.mode('MANUAL');await service.close()
            self.assertTrue(service.identity_task.cancelled());bridge.start_live.assert_not_awaited()

    async def test_untimed_but_complete_year_index_identity_reconciles_without_extra_request(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info') as fetch:
            bridge,service=self.setup_bridge(temp)
            service.published=[{'path':VEGAS_PATH,'year':2026,'start':info()['StartDate'],'session':'Race',
                                'event':'Las Vegas Grand Prix','circuit':{'Key':99903},'meetingKey':99902,'sessionKey':99901}]
            await service.tick(NOW)
            self.assertEqual(service.machine.state,'LIVE');fetch.assert_not_called()
            self.assertEqual(bridge.live_expected['identitySource'],'live-feed-plus-year-index')
            self.assertEqual(service.snapshot()['providerIdentityCheck']['state'],'year-index-confirmed')
            bridge.start_live.assert_not_awaited();await service.close()

    async def test_reconciliation_never_reopens_a_confirmed_completed_session(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info',return_value=confirmation()):
            bridge,service=self.setup_bridge(temp)
            service.machine.completed=[VEGAS_PATH]
            await service.tick(NOW);await service.identity_task;await service.tick(NOW+1)
            self.assertEqual(service.machine.reconciliation['reason'],'session-already-completed')
            self.assertEqual(service.snapshot()['view'],'dashboard');bridge.start_live.assert_not_awaited()
            self.assertIsNone(bridge.live_expected);await service.close()

    async def test_discovery_preserves_raw_session_key_even_when_time_filter_drops_entry(self):
        from bridge.archive import list_sessions
        from bridge.autonomous import combine_schedule
        meeting=info()['Meeting']
        meeting['Sessions']=[{'Key':99901,'Path':VEGAS_PATH,'Name':'Race','StartDate':info()['StartDate']}]
        with patch('bridge.archive.small_json',return_value={'Meetings':[meeting]}):rows=list_sessions(2026)
        self.assertEqual(rows[0]['sessionKey'],99901)
        self.assertIsNone(rows[0]['gmtOffset']);self.assertEqual(combine_schedule(rows,[]),[])
        self.assertIsNotNone(reconcile(NOW,advice(),observation(),catalog=rows)[0])

    async def test_auto_restart_observes_current_feed_but_does_not_claim_live_until_verified(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.live_reconciliation.published_session_info',return_value=confirmation()):
            bridge,service=self.setup_bridge(temp)
            bridge.source_task=None;bridge.state.topics={};bridge.state.upstream='idle';bridge.last_live_delta=None
            await service.tick(NOW)
            bridge.start_live.assert_awaited_once_with(None)
            self.assertEqual(service.snapshot()['view'],'dashboard')
            # Even if a failed observer ends immediately, no per-tick retry.
            await service.tick(NOW+.1);self.assertEqual(bridge.start_live.await_count,1)
            bridge.source_task=SimpleNamespace(done=lambda:False)
            bridge.state.upstream='connected';bridge.last_live_delta=NOW+1
            bridge.state.topics={'SessionInfo':info(),'SessionStatus':{'Status':'Started'},
                                 'Position.z':{'1':{'X':100,'Y':200,'_sampleTimeMs':(NOW+1)*1000}}}
            await service.tick(NOW+1);await service.identity_task;await service.tick(NOW+2)
            self.assertEqual(service.machine.state,'LIVE');self.assertEqual(service.snapshot()['view'],'live')
            self.assertEqual(bridge.start_live.await_count,1)
            bridge.stop_source.assert_not_awaited();await service.close()
