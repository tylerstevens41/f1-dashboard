"""Synthetic discovery fixtures only; no real Mexico success claim."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge.window_scan import find_usable_window, ScanUnavailable
from bridge.tests.test_calibration import dataset
from bridge.tests.test_preparation import identity,session
from bridge.preparation import collect_geometry


FEEDS={topic:{'StreamPath':topic+'.jsonStream'} for topic in ('TimingData','Position.z')}


def records(path,budget):
    if 'TimingData' in path:
        budget[0]+=100
        yield '1.03:46:40.000'+json.dumps({'Lines':{str(i):{'NumberOfLaps':1,'InPit':False} for i in range(1,4)}})
    else:
        for second,payload in [('40','zero'),('41','first'),('42','moving')]:
            budget[0]+=100
            yield '1.03:46:'+second+'.000'+json.dumps(payload)


def decode(topic,payload):
    offset={'zero':0,'first':10,'moving':20}[payload]
    return {str(i):{'DriverNo':str(i),'X':offset,'Y':0,'Status':'OnTrack','Utc':f'2026-11-01T20:00:{offset//10:02}.000Z'} for i in range(1,4)}


class WindowScanTests(unittest.TestCase):
    def test_requires_real_lap_timing_nonzero_positions_and_movement(self):
        stats={}
        with patch('bridge.window_scan.small_json',return_value={'Feeds':FEEDS}),patch('bridge.window_scan.lines',side_effect=records),patch('bridge.window_scan.decode',side_effect=decode):
            at=find_usable_window('2026/Unit/',93356,stats)
        self.assertEqual(at,100002);self.assertEqual(stats['movingDrivers'],3)
        self.assertEqual(stats['zeroCoordinateRecords'],3);self.assertEqual(stats['timedDrivers'],3)
        self.assertEqual(stats['status'],'candidate');self.assertGreater(stats['bytesRead'],0)
        self.assertNotIn('DriverNo',json.dumps(stats));self.assertNotIn('2026-11',json.dumps(stats))

    def test_zero_only_data_never_produces_candidate_geometry(self):
        stats={}
        with patch('bridge.window_scan.small_json',return_value={'Feeds':FEEDS}),patch('bridge.window_scan.lines',side_effect=records),patch('bridge.window_scan.decode',return_value=decode('Position.z','zero')):
            with self.assertRaises(ScanUnavailable) as error:find_usable_window('2026/Unit/',93356,stats)
        self.assertEqual(error.exception.code,'no-moving-gps-in-bounded-source')
        self.assertEqual(stats['movingDrivers'],0);self.assertEqual(stats['status'],'failed')

    def test_no_lap_timing_stops_without_position_download(self):
        def empty_timing(path,budget):
            self.assertIn('TimingData',path)
            yield '1.03:46:40.000'+json.dumps({'Lines':{'1':{'NumberOfLaps':0}}})
        with patch('bridge.window_scan.small_json',return_value={'Feeds':FEEDS}),patch('bridge.window_scan.lines',side_effect=empty_timing):
            with self.assertRaises(ScanUnavailable) as error:find_usable_window('2026/Unit/',93356,{})
        self.assertEqual(error.exception.code,'no-lap-timing-in-bounded-source')

    def test_record_limit_and_auth_errors_are_preserved(self):
        with patch('bridge.window_scan.small_json',return_value={'Feeds':FEEDS}),patch('bridge.window_scan.lines',side_effect=records),patch('bridge.window_scan.decode',side_effect=decode):
            with self.assertRaises(ScanUnavailable) as error:find_usable_window('2026/Unit/',93356,{},max_records=2)
        self.assertEqual(error.exception.code,'scan-limit')
        from bridge.archive import ArchiveUnavailable
        stats={}
        with patch('bridge.window_scan.small_json',side_effect=ArchiveUnavailable('SECRET_TOKEN',code='authentication-required')):
            with self.assertRaises(ArchiveUnavailable):find_usable_window('2026/Unit/',93356,stats)
        self.assertNotIn('SECRET_TOKEN',json.dumps(stats))

    def test_zero_cached_window_can_discover_later_measured_candidate_then_build(self):
        meta=identity(session());calls=[];scans=[]
        data=dataset()
        def extract(clip,diagnostics=None):
            if clip.get('zero'):
                return [{**p,'x':0,'y':0,'lap':None} for p in data['samples']]
            return data['samples']
        def fetch(path,offset,duration,**kwargs):
            calls.append(offset)
            return {'zero':offset==92876,'synthetic':True,'originMs':0,'initial':{'SessionInfo':{'Meeting':{'Circuit':{'Key':65}}}},'events':[]}
        def scan(path,after,stats,**kwargs):
            scans.append(after);stats.update(status='candidate',candidateOffset=100002,movingDrivers=3)
            return 100002
        with tempfile.TemporaryDirectory() as root,patch('bridge.archive.fetch_clip',side_effect=fetch),patch('bridge.calibrate.collect_clip',side_effect=extract),patch('bridge.window_scan.find_usable_window',side_effect=scan):
            result=collect_geometry(meta,Path(root)/'gps-cache',lambda **_:None,windows=(92876,))
            report=json.loads((Path(root)/meta['assetKey']/'geometry-diagnostics.json').read_text())
        self.assertEqual(calls,[92876,100002]);self.assertEqual(scans,[93356])
        self.assertEqual(report['windows'][0]['invalidSampleReasons']['zeroCoordinates'],len(data['samples']))
        self.assertEqual(report['windows'][1]['windowSource'],'measured-lap-timing-and-moving-gps')
        self.assertTrue(result['validation']['automaticChecksPassed']);self.assertTrue(result['provenance']['synthetic'])
