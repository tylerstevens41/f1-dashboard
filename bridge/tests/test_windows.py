import base64
import json
import unittest
import zlib
from bridge.windows import recommend_windows


class WindowTests(unittest.TestCase):
    def test_only_loaded_ontrack_real_format_samples_are_ranked(self):
        raw={'Position':[{'Timestamp':'1970-01-01T00:00:01Z','Entries':{
            '1':{'X':10,'Y':20,'Status':'OnTrack'},'2':{'X':20,'Y':30,'Status':'OffTrack'}}}]}
        compressor=zlib.compressobj(wbits=-15)
        payload=base64.b64encode(compressor.compress(json.dumps(raw).encode())+compressor.flush()).decode()
        clip={'originMs':0,'startOffsetSeconds':600,'initial':{},'events':[{'offsetMs':1000,'topic':'Position.z','payload':payload}]}
        windows=recommend_windows(clip)
        self.assertEqual(len(windows),1)
        self.assertEqual(windows[0]['onTrackDrivers'],1)
        self.assertEqual(windows[0]['archiveOffsetSeconds'],600)
