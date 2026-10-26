"""Synthetic protocol unit fixtures only; not race recordings or calibration evidence."""
import asyncio
import base64
import json
import unittest
import zlib
from bridge.live import DashboardClient
from bridge.protocol import RaceState, decode, merge, utc_ms


def compressed(value):
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return base64.b64encode(compressor.compress(json.dumps(value).encode()) + compressor.flush()).decode()


class ProtocolTests(unittest.TestCase):
    def test_nested_array_delta_deletion_and_null(self):
        original = {'Stints':[{'Compound':'MEDIUM','TotalLaps':4}], 'Other':7}
        merged = merge(original,{'Stints':{'0':{'TotalLaps':5},'1':{'Compound':'HARD'}}})
        self.assertEqual(merged['Stints']['0'],{'Compound':'MEDIUM','TotalLaps':5})
        self.assertEqual(merge(merged,{'Stints':{'_deleted':['0']}})['Stints'],{'1':{'Compound':'HARD'}})
        self.assertEqual(merge(merged,{'Other':None})['Other'],None)
        self.assertIsInstance(original['Stints'],list)

    def test_driver_identity_and_incremental_timing(self):
        state = RaceState()
        state.ingest('DriverList',{'1':{'Tla':'VER','TeamColour':'123456'}})
        state.ingest('DriverList',{'1':{'FullName':'Example'}})
        self.assertEqual(state.topics['DriverList']['1']['Tla'],'VER')
        state.ingest('TimingData',{'Lines':{'1':{'BestLapTime':{'Value':'1:30.000'},'Position':'2'}}})
        state.ingest('TimingData',{'Lines':{'1':{'Position':'1'}}})
        self.assertEqual(state.topics['TimingData']['1']['BestLapTime']['Value'],'1:30.000')
        state.ingest('TimingAppData',{'Lines':{'1':{'Stints':[{'Compound':'HARD','TotalLaps':2}]}}})
        state.ingest('TimingAppData',{'Lines':{'1':{'Stints':{'0':{'TotalLaps':3}}}}})
        self.assertEqual(state.topics['TimingAppData']['1']['Stints']['0']['Compound'],'HARD')

    def test_session_change_clears_all_previous_topics(self):
        state = RaceState()
        state.ingest('SessionInfo',{'Key':1,'Path':'same/','Meeting':{'Name':'A'}})
        state.ingest('DriverList',{'1':{'Tla':'OLD'}})
        generation = state.generation
        state.ingest('SessionInfo',{'Path':'same/'})
        self.assertIn('DriverList',state.topics)
        self.assertEqual(state.generation,generation)
        messages = state.ingest('SessionInfo',{'Key':2,'Meeting':{'Name':'B'}})
        self.assertNotIn('DriverList',state.topics)
        self.assertGreater(state.generation,generation)
        self.assertEqual(messages[0]['type'],'snapshot')

    def test_installed_livef1_gps_and_car_decoders(self):
        stamp = '2024-10-20T19:00:00Z'
        position = compressed({'Position':[{'Timestamp':stamp,'Entries':{'1':{'X':10,'Y':20,'Z':0,'Status':'OnTrack'}}}]})
        state = RaceState('TEST')
        state.ingest('Position.z',position,clock_ms=utc_ms(stamp))
        point = state.topics['Position.z']['1']
        self.assertEqual((point['X'],point['Y']),(10,20))
        older = compressed({'Position':[{'Timestamp':'2024-10-20T18:59:59Z','Entries':{'1':{'X':999,'Y':999}}}]})
        state.ingest('Position.z',older,clock_ms=utc_ms(stamp))
        self.assertEqual(state.topics['Position.z']['1']['X'],10)
        car = compressed({'Entries':[{'Utc':stamp,'Cars':{'1':{'Channels':{'2':12000,'0':300}}}}]})
        self.assertIn('1',decode('CarData.z',car))

    def test_bounded_race_control(self):
        state = RaceState()
        for i in range(130):
            state.ingest('RaceControlMessages',{'Messages':{str(i):{'Message':str(i)}}})
        self.assertEqual(len(state.topics['RaceControlMessages']['Messages']),100)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_snapshot_and_feed_use_same_normalizer(self):
        state = RaceState()
        async def emit(topic,payload,timestamp):
            state.ingest(topic,payload,timestamp)
        async def status(_):
            pass
        resets=[]
        async def snapshot():
            resets.append(True)
        client = DashboardClient(emit,status,snapshot)
        await client._dispatch({'type':3,'result':{'DriverList':{'4':{'Tla':'NOR'}},'TimingAppData':{'Lines':{'4':{'Stints':[{'Compound':'SOFT'}]}}}}})
        await client._dispatch({'target':'feed','arguments':['TimingAppData',{'Lines':{'4':{'Stints':{'0':{'TotalLaps':4}}}}},None]})
        self.assertEqual(len(resets),1)
        self.assertEqual(state.topics['TimingAppData']['4']['Stints']['0'],{'Compound':'SOFT','TotalLaps':4})
        self.assertEqual(state.topics['DriverList']['4']['RacingNumber'],'4')


if __name__ == '__main__':
    unittest.main()
