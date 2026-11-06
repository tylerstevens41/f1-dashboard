"""Synthetic figure-eight fixtures; never real Suzuka validation evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
import numpy as np
from bridge.calibrate import build,clean_laps,write_json
from bridge.preparation import collect_geometry
from bridge.trajectory_order import direction_consensus,crossover_audit


def eight(t):
    return np.column_stack([10000+5000*(np.sin(t)+.30*np.cos(3*t)+.17*np.sin(2*t)),7000+2200*(np.sin(2*t)+.22*np.cos(4*t))])


def dataset():
    samples=[]
    points=eight(np.linspace(.3,2*np.pi+.3,241))
    for lap in range(1,7):
        for i,p in enumerate(points):
            time=lap*150000+i*400
            samples.append(dict(driver=str(lap%2+1),lap=lap,time=time,frameTime=time,x=float(p[0]),y=float(p[1]),status='OnTrack',inPit=False,pitOut=False))
    return dict(schema='livef1-calibration-samples-v1',source='LiveF1',synthetic=True,circuitId='figure-eight-fixture',sessionPath='synthetic-only',samples=samples)


class FigureEightTests(TestCase):
    def test_cancelled_area_does_not_mean_wrong_direction(self):
        laps,_=clean_laps(dataset())
        self.assertEqual(len(laps),6)
        self.assertTrue(direction_consensus(laps)['passed'])
        reversed_laps=copy.deepcopy(laps);reversed_laps[2]['points']=reversed_laps[2]['points'][::-1]
        self.assertFalse(direction_consensus(reversed_laps)['passed'])
        phase=copy.deepcopy(laps);phase[2]['points']=np.roll(phase[2]['points'],15,axis=0)
        self.assertTrue(direction_consensus(phase)['passed'])

    def test_build_preserves_order_and_reports_separate_crossover_visits(self):
        calibration=build(dataset(),layout='figure-eight-fixture-v1')
        self.assertTrue(calibration['validation']['automaticChecksPassed'])
        self.assertFalse(calibration['validation']['verified'])
        p=np.array([[p['x'],p['y']] for p in calibration['geometry']['points']])
        audit=crossover_audit(p)
        self.assertTrue(audit['projectedCrossings']);self.assertFalse(audit['heightVerified'])
        for crossing in audit['projectedCrossings']:
            a,b=crossing['fractions'];self.assertGreater(min(abs(a-b),1-abs(a-b)),.1)
        self.assertLess(np.max(np.linalg.norm(np.diff(p,axis=0),axis=1))/np.linalg.norm(np.ptp(p,axis=0)),.04)

    def test_coordinator_accepts_cached_cancelled_area_without_downloading(self):
        data=dataset();meta=dict(id=data['circuitId'],layoutVersion='fixture-v1',circuitKey='fixture',assetKey='circuit-fixture-2026',year=2026,path=data['sessionPath'])
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/'gps-cache';cache.mkdir();token=hashlib.sha256(f"{meta['path']}:5400:480:extraction-v2".encode()).hexdigest()
            write_json(cache/f'{token}.json.gz',data)
            # Force the numerically cancelled/mixed-area branch independently of
            # platform roundoff; real lap arrays remain ordered measured fixtures.
            original=np.sum
            def area_sum(value,*args,**kwargs):
                return 0. if np.asarray(value).shape==(512,) else original(value,*args,**kwargs)
            with patch('bridge.archive.fetch_clip',side_effect=AssertionError('must reuse cache')),patch('numpy.sum',side_effect=area_sum):
                result=collect_geometry(meta,cache,lambda **_:None,windows=(5400,))
            window=result['validation']['preparationDiagnostics']['windows'][0]
            self.assertEqual(window['status'],'accepted');self.assertTrue(window['orderedDirection']['passed'])
            self.assertTrue(result['provenance']['synthetic'])

    def test_real_boundary_math_on_ordered_asymmetric_crossover_fixture(self):
        from bridge.corner_import import align,project_corner,ImportFailure
        from bridge.sector_import import add_boundaries
        t=np.linspace(.3,.3+2*np.pi,257)[:-1];reference=eight(t)
        target=reference*1.7+np.array([2000,-3000]);closed=np.vstack([target,target[0]])
        corners=[{'number':i+1,'letter':'','x':float(reference[j,0]),'y':float(reference[j,1]),'angle':45,'distance':None} for i,j in enumerate([20,55,88,150,190,225])]
        source=dict(schema='fastf1-circuit-source-v1',circuitId='fixture',layoutVersion='v1',year=2026,event='synthetic-only',session='R',corners=corners,reference=reference.tolist(),rotation=0)
        calibration=dict(schema='livef1-circuit-calibration-v1',source='LiveF1',circuitId='fixture',layoutVersion='v1',geometry={'points':[{'x':float(p[0]),'y':float(p[1])} for p in closed]})
        laps=[];r=np.vstack([reference,reference[0]])
        for i in range(7):
            start=1000+i*120;times=start+np.arange(-.4,100.5,.2);phase=((times-start)/100+.12)%1
            xy=np.column_stack([np.interp(phase*256,np.arange(257),r[:,j]) for j in range(2)])
            laps.append(dict(driver=str(i%3+1),lap=i+1,start=start,end=start+100,lapTime=100,s1=23,s2=42,s3=35,accurate=True,pit=False,generated=False,trackStatus='1',clockChecked=True,positions=np.column_stack([times,xy]).tolist()))
        source['boundaryLaps']=dict(schema='fastf1-boundary-laps-v1',laps=laps,rejected={})
        aligned=align(source,calibration,'fixture','v1');result=add_boundaries(source,aligned,calibration)
        self.assertEqual(result['direction'],1);self.assertEqual(len(result['corners']),6)
        self.assertEqual(result['boundaryDiagnostics']['validLaps'],7)
        self.assertTrue(all(result[k]['status']=='provisional' for k in ('startFinish','sector1End','sector2End')))
        # Ambiguous XY at a true crossover is rejected rather than switching arcs.
        crossing=crossover_audit(closed)['projectedCrossings'][0]
        i=crossing['segments'][0];j=crossing['segments'][1]
        a,b=closed[i],closed[i+1];c,d=closed[j],closed[j+1]
        ratio=np.linalg.solve(np.column_stack([b-a,-(d-c)]),c-a)[0];point=a+ratio*(b-a)
        with self.assertRaisesRegex(ImportFailure,'Ambiguous'):project_corner(point,closed,float(np.linalg.norm(np.ptp(closed,axis=0))))

    def test_offline_audit_preserves_assets_and_refuses_overwrite(self):
        import sys
        from bridge.preparation_audit import main
        with tempfile.TemporaryDirectory() as temp:
            report=Path(temp)/'audit.json'
            args=['audit','--year','2026','--event','Suzuka','--store',str(Path(temp)/'store'),'--report',str(report)]
            with patch.object(sys,'argv',args):self.assertEqual(main(),1)
            data=json.loads(report.read_text());self.assertEqual(data['state'],'not-prepared');self.assertEqual(data['circuits'],[])
            before=report.read_bytes()
            with patch.object(sys,'argv',args),self.assertRaises(SystemExit):main()
            self.assertEqual(report.read_bytes(),before)

    def test_synthetic_geometry_cannot_be_published_as_real_preparation(self):
        from bridge.corner_import import geometry_id
        from bridge.preparation import validate_bundle,PreparationError
        calibration=build(dataset(),layout='v1')
        bundle=dict(schema='prepared-circuit-v1',toolVersion=1,identity={'id':calibration['circuitId'],'layoutVersion':'v1'},calibration=calibration,geometryId=geometry_id([[p['x'],p['y']] for p in calibration['geometry']['points']]))
        with self.assertRaisesRegex(PreparationError,'real-data'):validate_bundle(bundle)

    def test_audit_reports_stored_window_and_partial_annotations_without_mutation(self):
        from bridge.preparation_audit import audit_bundle
        from bridge.tests.test_preparation import bundle,annotation
        prepared=bundle();prepared['calibration']['provenance']['preparationWindowSeconds']=1234
        prepared['corners']=annotation(prepared)
        before=copy.deepcopy(prepared)
        report=audit_bundle(prepared,Path('synthetic-fixture-only'))
        self.assertEqual(report['state'],'geometry-ready')
        self.assertEqual(report['annotations']['corners'],1)
        self.assertEqual(report['testPlayback']['offsetSeconds'],1234)
        self.assertFalse(report['testPlayback']['verified'])
        self.assertEqual(prepared,before)
