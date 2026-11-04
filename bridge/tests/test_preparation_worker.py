"""Run in .venv-fastf1: cached synthetic input; no LiveF1 import needed."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from bridge.tests.test_sector_import import lap_fixture


class PreparationWorkerTests(unittest.TestCase):
    def test_dedicated_interpreter_cached_source_exports_twenty_corners_and_boundaries(self):
        source,calibration,_,_=lap_fixture()
        source.update(circuitKey=65,provider='synthetic-unit-fixture')
        meta={'id':'test','layoutVersion':'v1','circuitKey':'65','year':2026,'event':'synthetic','session':'R','path':'synthetic-only'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'sources';cache.mkdir()
            token=hashlib.sha256(meta['path'].encode()).hexdigest()
            (cache/f'{token}.json').write_text(json.dumps(source))
            cal=root/'calibration.json';cal.write_text(json.dumps(calibration));before=cal.read_bytes()
            request={'identity':meta,'calibration':str(cal),'output':str(root/'output.json'),'cache':str(root/'fastf1-cache'),'sourceCache':str(cache)}
            path=root/'request.json';path.write_text(json.dumps(request))
            result=subprocess.run([sys.executable,'-m','bridge.preparation_worker','--request',str(path)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            output=json.loads((root/'output.json').read_text())
            self.assertEqual(len(output['corners']['corners']),20)
            self.assertIsNotNone(output['sectors']['startFinish'])
            self.assertTrue(all(output['sectors'][k]['status']=='provisional' for k in ('startFinish','sector1End','sector2End')))
            self.assertNotIn('importSource',output['corners']);self.assertNotIn('importSource',output['sectors'])
            self.assertEqual(cal.read_bytes(),before)

    def test_missing_cached_source_does_not_invent_annotations(self):
        from unittest.mock import patch
        from bridge.preparation_worker import run
        from bridge.corner_import import ImportFailure
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cal=root/'cal.json';cal.write_text('{}')
            request={'identity':{'path':'unit','year':2026,'event':'unit','session':'Race'},'calibration':str(cal),'output':str(root/'output.json'),'cache':str(root/'cache'),'sourceCache':str(root/'sources')}
            with patch('bridge.preparation_worker.fetch',side_effect=ImportFailure('Fixture source unavailable')):
                run(request)
            result=json.loads((root/'output.json').read_text())
            self.assertIsNone(result['corners']);self.assertIsNone(result['sectors']);self.assertTrue(result['warnings'])
