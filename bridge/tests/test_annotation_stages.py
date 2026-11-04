"""Synthetic staged FastF1 fixtures; no real annotation/download success claim."""
import copy
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
from bridge.annotation_progress import Progress,FastF1Stages,atomic
from bridge.preparation import import_annotations,prepare,AssetStore,PreparationError
from bridge.preparation_worker import run
from bridge.tests.test_sector_import import lap_fixture
from bridge.tests.test_preparation import session,identity,calibration,bundle,annotation


def request(root):
    source,cal,*_=lap_fixture();source.update(circuitKey=65,provider='synthetic-unit-fixture')
    meta={'id':'test','layoutVersion':'v1','circuitKey':'65','year':2026,'event':'synthetic','session':'R','path':'synthetic-only'}
    cal_path=root/'cal.json';cal_path.write_text(json.dumps(cal))
    value={'identity':meta,'calibration':str(cal_path),'output':str(root/'out.json'),'cache':str(root/'cache'),
           'sourceCache':str(root/'sources'),'checkpoints':str(root/'checkpoints'),'diagnostics':str(root/'diagnostics.json')}
    return value,source,cal


class AnnotationStageTests(unittest.TestCase):
    def test_corners_publish_before_multi_lap_collection_and_survive_collection_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);req,source,cal=request(root);before=(root/'cal.json').read_bytes()
            def fetch(*args,**kwargs):
                partial=copy.deepcopy(source);partial.pop('boundaryLaps')
                kwargs['progress']('fastf1-telemetry-load')
                kwargs['source_ready'](partial)
                output=json.loads((root/'out.json').read_text())
                self.assertEqual(len(output['corners']['corners']),20);self.assertIsNone(output['sectors'])
                kwargs['progress']('multi-lap-collection')
                raise RuntimeError('SECRET_TOKEN upstream response')
            with patch('bridge.preparation_worker.fetch',side_effect=fetch):run(req)
            output=json.loads((root/'out.json').read_text())
            diag=json.loads((root/'diagnostics.json').read_text())
            self.assertEqual(diag['failedPhase'],'multi-lap-collection');self.assertEqual(diag['state'],'incomplete')
            self.assertEqual(len(output['corners']['corners']),20);self.assertIsNone(output['sectors'])
            self.assertNotIn('SECRET_TOKEN',json.dumps(output)+json.dumps(diag))
            self.assertTrue(list((root/'checkpoints').glob('*-corners.json')))
            self.assertEqual(before,(root/'cal.json').read_bytes())
            # Retry: cached corner checkpoint is already visible while source
            # acquisition is retried for missing sector input.
            def succeed(*args,**kwargs):
                self.assertEqual(len(json.loads((root/'out.json').read_text())['corners']['corners']),20)
                kwargs['source_ready'](copy.deepcopy(source))
                return copy.deepcopy(source)
            with patch('bridge.preparation_worker.fetch',side_effect=succeed):run(req)
            output=json.loads((root/'out.json').read_text());self.assertIsNotNone(output['sectors'])
            with patch('bridge.preparation_worker.fetch',side_effect=AssertionError('Completed checkpoints must not fetch')):
                run(req)
            self.assertEqual(json.loads((root/'out.json').read_text())['sectors'],output['sectors'])

    def test_shared_fetch_gets_metadata_before_telemetry_and_sources_before_sector_laps(self):
        from types import SimpleNamespace
        import pandas as pd
        from bridge.corner_import import fetch
        source,_,reference,_=lap_fixture();timeline=[];telemetry=[False];metadata=[]
        rows=[{'Number':c['number'],'Letter':c['letter'],'X':c['x'],'Y':c['y'],'Angle':c['angle'],'Distance':c['distance']} for c in source['corners']]
        def load(**kwargs):
            timeline.append(('load',kwargs));telemetry[0]=kwargs.get('telemetry',True)
        def circuit_info():
            timeline.append(('info',telemetry[0]));frame=pd.DataFrame(rows)
            if not telemetry[0]:frame['Distance']=float('nan')
            return SimpleNamespace(rotation=source['rotation'],corners=frame)
        lap=SimpleNamespace(Driver='1',LapNumber=3,get_pos_data=lambda:pd.DataFrame(reference,columns=['X','Y']))
        session=SimpleNamespace(load=load,get_circuit_info=circuit_info,laps=SimpleNamespace(pick_fastest=lambda:lap),
            event=SimpleNamespace(EventName='Synthetic'),session_info={'Meeting':{'Circuit':{'Key':65}}})
        fake=SimpleNamespace(__version__='3.9.0',get_session=Mock(return_value=session),Cache=Mock())
        def ready(value):timeline.append(('source',len(value['reference'])))
        def collector(value,progress=None):
            self.assertTrue(any(k=='source' for k,*_ in timeline));timeline.append(('laps',40))
            if progress:progress(inspected=7,accepted=7,rejected=0)
            return source['boundaryLaps']
        with tempfile.TemporaryDirectory() as temp,patch.dict('sys.modules',{'fastf1':fake}):
            value=fetch(2026,'synthetic','R',temp,lap_collector=collector,progress=lambda *a,**k:None,metadata_ready=metadata.append,source_ready=ready)
        self.assertEqual([entry for entry in timeline if entry[0]=='info'],[('info',False),('info',True)])
        self.assertIsNone(metadata[0]['corners'][0]['distance'])
        self.assertEqual(value['corners'],source['corners']);self.assertEqual(value['reference'],source['reference'])
        self.assertEqual(value['boundaryLaps'],source['boundaryLaps'])
        self.assertEqual(timeline[0][1],{'telemetry':False,'weather':False,'messages':False})
        self.assertEqual([v for k,v in timeline if k=='load'][1],{'laps':False,'telemetry':True,'weather':False,'messages':False})

    def test_timeout_retains_corner_checkpoint_and_reports_exact_stalled_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);exe=root/'python';exe.touch();meta=identity(session());cal=calibration(meta)
            reports=[];ticks=[0]
            def now():ticks[0]+=1;return ticks[0]
            class Process:
                returncode=None
                def poll(self):return self.returncode
                def kill(self):self.returncode=-9
                def wait(self):return self.returncode
            def factory(args,**options):
                self.assertEqual(options['stderr'],subprocess.DEVNULL)
                req=json.loads(Path(args[-1]).read_text());p=Progress(req['diagnostics']);p.event('multi-lap-collection',inspected=2,accepted=1)
                b=bundle();atomic(req['output'],{'corners':annotation(b),'sectors':None,'warnings':[]})
                return Process()
            with patch('bridge.preparation.fast_python',return_value=exe):
                corners,sectors,warnings=import_annotations(meta,cal,root,lambda **v:reports.append(v),process_factory=factory,timeout=2,clock=now,sleep=lambda _:None)
            self.assertIsNotNone(corners);self.assertIsNone(sectors)
            self.assertIn('multi-lap-collection',warnings[-1])
            diag=json.loads((root/meta['assetKey']/'annotation-diagnostics.json').read_text())
            self.assertTrue(diag['timedOut']);self.assertEqual(diag['phase'],'multi-lap-collection')
            self.assertTrue(any(r.get('annotationPartial',{}).get('corners') for r in reports))

    def test_partial_annotation_event_is_published_before_importer_returns_without_geometry_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            store=AssetStore(temp);b=bundle();store.publish(b);original=copy.deepcopy(b['calibration'])
            def importer(meta,cal,root,report):
                report(stage='annotation-checkpoint',state='preparing',annotationPartial={'corners':annotation(b),'sectors':None})
                loaded=store.get(meta)
                self.assertIsNotNone(loaded['corners']);self.assertFalse(loaded['complete'])
                self.assertEqual(loaded['calibration'],original)
                return None,None,['Fixture sector timeout']
            out=prepare(session(),store,importer=importer,annotations_only=True,collector=Mock(side_effect=AssertionError('GPS must never run')))
            self.assertEqual(out['calibration'],original);self.assertIsNotNone(out['corners']);self.assertFalse(out['complete'])
            with self.assertRaises(PreparationError):prepare({**session(),'year':2025},store,annotations_only=True)

    def test_progress_only_exports_known_stages_not_logging_arguments(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'diagnostics.json';progress=Progress(path);handler=FastF1Stages(progress.event)
            for msg,args in [('Fetching car data...',()),('Parsing car data...',()),('Fetching position data...',()),('SECRET_TOKEN %s',('SECRET_ARGUMENT',))]:
                handler.emit(logging.LogRecord('fastf1.api',logging.INFO,'upstream.py',10,msg,args,None))
            data=json.loads(path.read_text());text=json.dumps(data)
            self.assertNotIn('SECRET',text);self.assertEqual(data['phase'],'position-data-download')
            self.assertTrue(all('at' in event and 'elapsedSeconds' in event for event in data['events']))
            self.assertIn('car-data-parse',data['phaseDurationsSeconds'])
