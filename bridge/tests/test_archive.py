import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.archive import ArchiveUnavailable, elapsed_ms, fetch_clip, load_recording, safe_url, save_clip, validate_clip, prune_cache, TopicUnavailable


class ArchiveTests(unittest.TestCase):
    def test_timestamp_and_url_constraints(self):
        self.assertEqual(elapsed_ms('01:02:03.456'),3723456)
        for path in ['https://evil.example/a','../secrets','http://livetiming.formula1.com/static/test']:
            with self.assertRaises(ValueError): safe_url(path)

    def test_bounded_window_seeds_prior_timing_and_caches(self):
        # Synthetic raw-format fixtures used to test ordering and seeds only.
        feeds = {t:{'StreamPath':t+'.jsonStream'} for t in ['SessionInfo','DriverList','TimingData','TimingAppData']}
        records = {
            'SessionInfo':[(0,{'Key':1,'Meeting':{'Circuit':{'ShortName':'Austin'}}})],
            'DriverList':[(0,{'1':{'Tla':'VER'}})],
            'TimingData':[(0,{'Lines':{'1':{'Position':'2','BestLapTime':{'Value':'1:20.0'}}}}),(11,{'Lines':{'1':{'Position':'1'}}})],
            'TimingAppData':[(0,{'Lines':{'1':{'Stints':[{'Compound':'HARD'}]}}})],
        }
        def stream(path,budget):
            topic = path.split('/')[-1].split('.jsonStream')[0]
            for second,value in records[topic]:
                yield f'00:00:{second:06.3f}'+json.dumps(value)
        with tempfile.TemporaryDirectory() as cache, patch('bridge.archive.small_json',return_value={'Feeds':feeds}),patch('bridge.archive.lines',side_effect=stream):
            clip = fetch_clip('2024/Test/Race/',10,5,cache)
            self.assertEqual(clip['initial']['TimingData']['1']['Position'],'2')
            self.assertEqual(clip['events'][0]['offsetMs'],1000)
            self.assertEqual(clip['capabilities']['Position.z'],'missing-stream')
            with patch('bridge.archive.small_json',side_effect=AssertionError('network should not be used')):
                self.assertEqual(fetch_clip('2024/Test/Race/',10,5,cache)['events'],clip['events'])

    def test_recording_round_trip_and_rejects_non_livef1(self):
        clip={'format':'livef1-clip-v1','source':'LiveF1','durationMs':1000,'originMs':0,'initial':{},'events':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'clip.json.gz'
            save_clip(path,clip)
            self.assertEqual(load_recording(path)['source'],'LiveF1')
        with self.assertRaises(ValueError):validate_clip({**clip,'source':'OpenF1'})
        with self.assertRaises(ValueError):validate_clip({**clip,'durationMs':9999999})

    def test_cache_keeps_only_three_clips(self):
        with tempfile.TemporaryDirectory() as directory:
            for i in range(5):
                (Path(directory)/f'{i}.json.gz').write_bytes(b'clip')
            prune_cache(directory)
            self.assertEqual(len(list(Path(directory).glob('*.json.gz'))),3)

    def test_missing_published_topic_is_reported_without_fake_data(self):
        with tempfile.TemporaryDirectory() as directory,patch('bridge.archive.small_json',return_value={'Feeds':{
            'SessionInfo':{'StreamPath':'SessionInfo.jsonStream'},'TimingData':{'StreamPath':'TimingData.jsonStream'}}}):
            def stream(path,budget):
                if 'TimingData' in path:
                    raise TopicUnavailable('404')
                yield '00:00:00.000'+json.dumps({'Key':1})
            with patch('bridge.archive.lines',side_effect=stream):
                clip=fetch_clip('2024/Test/',0,5,directory)
                self.assertEqual(clip['capabilities']['TimingData'],'missing')
                self.assertNotIn('TimingData',clip['initial'])

    def test_auth_failure_is_explicit_and_not_cached(self):
        with tempfile.TemporaryDirectory() as directory,patch('bridge.archive.small_json',side_effect=ArchiveUnavailable('HTTP 401')):
            with self.assertRaises(ArchiveUnavailable):fetch_clip('2024/Test/',0,5,directory)
            self.assertEqual(list(Path(directory).glob('*')),[])


if __name__ == '__main__':
    unittest.main()
