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

class SharedAustinMethodTests(unittest.TestCase):
    def test_worker_uses_the_exact_existing_import_and_boundary_function_objects(self):
        from bridge import preparation_worker,corner_import,sector_import
        self.assertIs(preparation_worker.fetch,corner_import.fetch)
        self.assertIs(preparation_worker.align,corner_import.align)
        self.assertIs(preparation_worker.collect_laps,sector_import.collect_laps)
        self.assertIs(preparation_worker.add_boundaries,sector_import.add_boundaries)

    def test_austin_and_mexico_worker_results_equal_direct_proven_functions(self):
        import copy
        from bridge.corner_import import align
        from bridge.sector_import import add_boundaries
        from bridge.preparation_worker import run
        # Identical synthetic geometry tests circuit-independent math; this is
        # neither a real Austin fixture nor a claim about Mexico corner count.
        fingerprints=[]
        for circuit,key,event in [('austin',63,'United States'),('mexico-city',65,'Mexico City')]:
            source,calibration,_,_=lap_fixture()
            layout=circuit+'-synthetic-unit-v1'
            source.update(circuitId=circuit,layoutVersion=layout,circuitKey=key,event=event,provider='synthetic-unit-fixture')
            calibration.update(circuitId=circuit,layoutVersion=layout)
            original_calibration=copy.deepcopy(calibration)
            direct_corners=align(source,calibration,circuit,layout)
            direct_sectors=add_boundaries(source,copy.deepcopy(direct_corners),calibration)
            meta={'id':circuit,'layoutVersion':layout,'circuitKey':str(key),'year':2026,'event':event,'session':'R','path':circuit+'-synthetic-only'}
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);cache=root/'sources';cache.mkdir()
                token=hashlib.sha256(meta['path'].encode()).hexdigest()
                (cache/f'{token}.json').write_text(json.dumps(source))
                cal=root/'cal.json';cal.write_text(json.dumps(calibration));before=cal.read_bytes()
                run({'identity':meta,'calibration':str(cal),'output':str(root/'out.json'),'cache':str(root/'cache'),'sourceCache':str(cache)})
                actual=json.loads((root/'out.json').read_text())
                self.assertEqual(cal.read_bytes(),before)
            self.assertEqual(calibration,original_calibration)
            if circuit=='austin':
                # Baseline matched the pre-refactor output exactly here. Round
                # only test numeric values for cross-platform BLAS tolerance;
                # actual functions/output are never rounded or changed.
                def stable(value):
                    if isinstance(value,float):return round(value,6)
                    if isinstance(value,dict):return {k:stable(v) for k,v in value.items()}
                    if isinstance(value,list):return [stable(v) for v in value]
                    return value
                baseline=hashlib.sha256(json.dumps(stable(actual['sectors']['boundaryDiagnostics']['fia']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
                self.assertEqual(baseline,'12d889a2bdf0d202cd21c9d534c30aaced0fde48fbb781d4e4c708f84928a3fe')
            self.assertEqual(actual['corners']['corners'],direct_corners['corners'])
            self.assertEqual(actual['corners']['alignment'],direct_corners['alignment'])
            for name in ('startFinish','sector1End','sector2End','direction','boundaryDiagnostics'):
                self.assertEqual(actual['sectors'][name],direct_sectors[name])
            self.assertTrue(all(actual['sectors'][k]['status']=='provisional' for k in ('startFinish','sector1End','sector2End')))
            fingerprints.append((actual['corners']['corners'],[actual['sectors'][k]['at'] for k in ('startFinish','sector1End','sector2End')]))
        self.assertEqual(fingerprints[0],fingerprints[1])

    def test_failed_sector_calculation_retains_corners_but_is_not_complete(self):
        from unittest.mock import patch
        from bridge.preparation_worker import run
        from bridge.corner_import import ImportFailure
        source,calibration,_,_=lap_fixture()
        source.update(circuitKey=65,provider='synthetic-unit-fixture')
        meta={'id':'test','layoutVersion':'v1','circuitKey':'65','year':2026,'event':'synthetic','session':'R','path':'synthetic-only'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'sources';cache.mkdir()
            token=hashlib.sha256(meta['path'].encode()).hexdigest()
            (cache/f'{token}.json').write_text(json.dumps(source))
            cal=root/'cal.json';cal.write_text(json.dumps(calibration))
            with patch('bridge.preparation_worker.add_boundaries',side_effect=ImportFailure('Fixture: insufficient valid crossing laps')):
                run({'identity':meta,'calibration':str(cal),'output':str(root/'out.json'),'cache':str(root/'cache'),'sourceCache':str(cache)})
            output=json.loads((root/'out.json').read_text())
        self.assertEqual(len(output['corners']['corners']),20)
        self.assertIsNone(output['sectors']);self.assertTrue(output['warnings'])
