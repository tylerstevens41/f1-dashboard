"""Synthetic coordinator fixtures only; no real Mexico accuracy claim."""
import asyncio
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
from bridge.preparation import (identity, AssetStore, prepare, PreparationError, validate_bundle,
                                atomic_json, prune_cache, import_annotations, batch, collect_geometry)
from bridge.corner_import import geometry_id


def session(key=65, name='Mexico City'):
    return {'path':'2026/unit/Race/', 'year':2026, 'event':'Mexico City Grand Prix', 'location':'Mexico City',
            'session':'Race', 'circuit':{'Key':key, 'ShortName':name}}


def calibration(meta):
    t=np.linspace(0,2*np.pi,257)
    points=[{'x':float(10000*np.cos(a)), 'y':float(6000*np.sin(a))} for a in t]
    points[-1]=points[0].copy()
    # Explicit simulated acceptance metadata tests storage mechanics, not accuracy.
    return {'schema':'livef1-circuit-calibration-v1','source':'LiveF1','circuitId':meta['id'],'layoutVersion':meta['layoutVersion'],
            'status':'candidate','mapping':{'matrix':[1,0,0,1,0,0]},'geometry':{'points':points},
            'validation':{'automaticChecksPassed':True,'verified':False},'provenance':{'synthetic':False,'testFixture':True}}


def bundle():
    meta=identity(session());cal=calibration(meta)
    return {'schema':'prepared-circuit-v1','toolVersion':1,'identity':meta,'calibration':cal,
            'geometryId':geometry_id([[p['x'],p['y']] for p in cal['geometry']['points']]),
            'corners':None,'sectors':None,'complete':False,'warnings':[]}


def annotation(b):
    return {'schema':'f1-circuit-annotations-v1','circuitId':b['identity']['id'],'layoutVersion':b['identity']['layoutVersion'],
            'geometryId':b['geometryId'],'direction':1,'corners':[{'number':1,'at':.1,'status':'provisional'}], 'startFinish':{'at':.99,'status':'provisional'},'sector1End':{'at':.2,'status':'provisional'},'sector2End':{'at':.75,'status':'provisional'}}


class PreparationTests(unittest.TestCase):
    def test_stable_key_across_event_aliases_but_not_seasons(self):
        a=session();b={**a,'event':'FORMULA 1 MEXICO CITY GRAND PRIX'}
        self.assertEqual(identity(a)['assetKey'],identity(b)['assetKey'])
        self.assertNotEqual(identity(a)['assetKey'],identity({**a,'year':2025})['assetKey'])
        self.assertEqual(identity(session(name='Circuit of the Americas'))['id'],'austin')
        with self.assertRaises(PreparationError):identity({**a,'circuit':{}})

    def test_atomic_publish_validates_identity_fingerprint_and_preserves_revision(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root);b=bundle();store.publish(b)
            original=store.get(b['identity'])
            bad=copy.deepcopy(b);bad['geometryId']='wrong'
            with self.assertRaises(PreparationError):store.publish(bad)
            self.assertEqual(store.get(b['identity']),original)
            store.publish(b)
            self.assertEqual(len(list(store.directory(b['identity']['assetKey']).glob('*.json'))),3)
            with self.assertRaises(PreparationError):store.directory('../../escape')

    def test_annotations_cannot_use_another_geometry_layout_or_direction(self):
        for field,value in [('geometryId','wrong'),('layoutVersion','other'),('direction',-1)]:
            b=bundle();b['corners']=annotation(b);b['corners'][field]=value
            with self.assertRaises(PreparationError):validate_bundle(b)
        b=bundle();b['calibration']['provenance']['synthetic']=True
        with self.assertRaises(PreparationError):validate_bundle(b)

    def test_progress_geometry_first_cached_reload_and_no_repeat_collection(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root);events=[];collector=Mock(side_effect=lambda meta,*a,**k:calibration(meta))
            def importer(meta,cal,root,report):
                self.assertIsNotNone(store.get(meta))
                report(stage='corners',state='preparing')
                b=store.get(meta)
                return annotation(b),annotation(b),[]
            first=prepare(session(),store,lambda **v:events.append(v),collector=collector,importer=importer)
            second=prepare(session(),store,collector=collector,importer=Mock(side_effect=AssertionError('must not rerun')))
            self.assertTrue(first['complete']);self.assertEqual(first,second);self.assertEqual(collector.call_count,1)
            self.assertIn('geometry-ready',[e['state'] for e in events])
            self.assertEqual(events[-1]['state'],'ready')

    def test_missing_annotations_retry_reuses_geometry_and_preserves_reviewed_corners(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root);b=bundle();b['corners']={**annotation(b),'provenance':'reviewed','manualCustom':{'at':.2}}
            store.publish(b)
            def importer(*_):return {'invalid':'would replace'},annotation(b),[]
            result=prepare(session(),store,retry=True,collector=Mock(side_effect=AssertionError()),importer=importer)
            self.assertEqual(result['corners'],b['corners']);self.assertTrue(result['complete'])

    def test_failure_leaves_geometry_and_records_safe_error(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root)
            with self.assertRaises(PreparationError):
                prepare(session(),store,collector=lambda meta,*a,**k:calibration(meta),importer=Mock(side_effect=RuntimeError('SECRET_TOKEN')))
            meta=identity(session());self.assertIsNotNone(store.get(meta))
            log=(store.directory(meta['assetKey'])/'job.json').read_text()
            self.assertNotIn('SECRET_TOKEN',log);self.assertIn('failed',log)
            self.assertFalse((store.directory(meta['assetKey'])/'.lock').exists())

    def test_duplicate_process_lock_and_interrupted_owner_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root);meta=identity(session());lock=store.acquire(meta)
            with self.assertRaises(PreparationError):store.acquire(meta)
            with patch('bridge.preparation.process_alive',return_value=False):
                recovered=store.acquire(meta)
            self.assertEqual(lock,recovered);lock.unlink()

    def test_atomic_failure_retains_current_pointer(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'current.json';atomic_json(p,{'revision':'old'})
            with patch('bridge.preparation.os.replace',side_effect=OSError):
                with self.assertRaises(OSError):atomic_json(p,{'revision':'new'})
            self.assertEqual(json.loads(p.read_text()),{'revision':'old'})
            self.assertEqual(len(list(Path(root).iterdir())),1)

    def test_bounded_cache_prunes_oldest_only(self):
        with tempfile.TemporaryDirectory() as root:
            for i in range(3):(Path(root)/f'{i}.json.gz').write_bytes(b'x'*10)
            (Path(root)/'reviewed.json').write_text('{}')
            prune_cache(root,limit=15)
            self.assertEqual(len(list(Path(root).glob('*.json.gz'))),1)
            self.assertTrue((Path(root)/'reviewed.json').exists())

    def test_separate_python_invocation_sanitizes_output_and_missing_environment(self):
        meta=identity(session())
        with tempfile.TemporaryDirectory() as root:
            executable=Path(root)/'python.exe';executable.touch()
            def runner(args,**options):
                self.assertEqual(args[:3],[str(executable),'-m','bridge.preparation_worker'])
                self.assertEqual(options['stdout'],subprocess.DEVNULL)
                request=json.loads(Path(args[-1]).read_text())
                atomic_json(request['output'],{'corners':None,'sectors':None,'warnings':['fixture missing data']})
                return Mock(returncode=0)
            with patch('bridge.preparation.fast_python',return_value=executable):
                _,_,warnings=import_annotations(meta,calibration(meta),root,lambda **_:None,runner=runner)
                self.assertEqual(warnings,['fixture missing data'])
            with patch('bridge.preparation.fast_python',return_value=Path(root)/'missing'):
                self.assertIn('environment missing',import_annotations(meta,calibration(meta),root,lambda **_:None)[2][0])

    def test_batch_resume_failure_continuation_and_austin_preservation(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root)
            s=[session(),session(),session(2,'Other'),session(3,'Austin')]
            def work(value,*args,**kwargs):
                if value['circuit']['Key']==2:raise PreparationError('fixture fail')
                return {'complete':True}
            with patch('bridge.preparation.prepare',side_effect=work) as mock:
                results=batch(s,store)
            self.assertEqual(mock.call_count,2)
            self.assertEqual([r['state'] for r in results],['complete','failed','existing-local-reference'])
            self.assertTrue((Path(root)/'batch.json').exists())

    def test_incomplete_gps_search_is_bounded_and_does_not_manufacture_outline(self):
        with tempfile.TemporaryDirectory() as root, patch('bridge.archive.fetch_clip',return_value={'initial':{'SessionInfo':{'Meeting':{'Circuit':{'Key':65}}}},'events':[]}), patch('bridge.calibrate.collect_clip',return_value=[]):
            with self.assertRaisesRegex(PreparationError,'2 bounded windows'):
                collect_geometry(identity(session()),root,lambda **_:None,windows=(1,2))

    def test_gps_build_does_not_require_svg_and_retains_direction(self):
        from bridge.calibrate import build
        from bridge.tests.test_calibration import dataset
        data=dataset();out=build(data,layout='synthetic-unit-v1')
        self.assertEqual(out['svgComparison']['decision'],'gps-derived-no-existing-svg')
        self.assertTrue(out['validation']['automaticChecksPassed'])
        self.assertTrue(out['provenance']['synthetic']);self.assertFalse(out['validation']['verified'])
        p=np.array([[r['x'],r['y']] for r in out['geometry']['points']])
        self.assertGreater(np.sum(p[:-1,0]*p[1:,1]-p[1:,0]*p[:-1,1]),0)


class PreparationBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_and_preparation_do_not_reset_playback_and_duplicate_jobs(self):
        from bridge.server import Bridge
        with tempfile.TemporaryDirectory() as root:
            bridge=Bridge(allow_test=True);bridge.configure_preparation(root,True)
            bridge.session_catalog[2026]=[session()]
            bridge.state.reset('TEST');bridge.state.playback='paused'
            before=bridge.state.generation
            bridge.send=Mock(side_effect=lambda *a:asyncio.sleep(0));bridge.broadcast=Mock(side_effect=lambda *a:asyncio.sleep(0))
            gate=asyncio.Event()
            async def pending(_):await gate.wait()
            with patch.object(bridge,'prepare_circuit',side_effect=pending) as worker:
                await bridge.command(None,{'action':'circuit-prepare','year':2026,'path':session()['path']})
                await bridge.command(None,{'action':'circuit-prepare','year':2026,'path':session()['path']})
                self.assertEqual(len(bridge.preparation_tasks),1)
                await asyncio.sleep(0);self.assertEqual(worker.call_count,1)
                gate.set();await asyncio.gather(*bridge.preparation_tasks.values())
            self.assertEqual(bridge.state.generation,before);self.assertEqual(bridge.state.playback,'paused')

    async def test_cached_assets_load_without_fastf1_and_lookup_after_restart(self):
        from bridge.server import Bridge
        with tempfile.TemporaryDirectory() as root:
            b=bundle();AssetStore(root).publish(b)
            bridge=Bridge();bridge.configure_preparation(root,False)
            sent=[]
            async def send(_,message):sent.append(message)
            bridge.send=send
            await bridge.command(None,{'action':'circuit-lookup','year':2026,'path':session()['path']})
            self.assertEqual(sent[0]['type'],'circuit-assets');self.assertEqual(sent[-1]['job']['state'],'ready')
            await bridge.command(None,{'action':'circuit-prepare','year':2026,'path':session()['path']})
            self.assertIn('--allow-prepare',sent[-1]['job']['error'])
