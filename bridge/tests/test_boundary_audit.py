import copy
import unittest
import numpy as np
from bridge.boundary_audit import arc_point,audit
from bridge.corner_import import geometry_id,ImportFailure,align
from bridge.sector_import import fia_check,collect_laps,add_boundaries
from bridge.physical_lines import apply_physical_lines
from bridge.tests.test_sector_import import lap_fixture

class BoundaryAuditTests(unittest.TestCase):
    def test_actual_austin_observations_reproduce_length_contradiction_not_correctness(self):
        # Medians of the 38 estimates in the attached report: observational inputs,
        # never promoted to verified boundary coordinates.
        s,a,b=.9962572732649239,.29711217736772716,.708877719002983
        result={'circuitId':'austin','sectorSource':{'year':2026},'direction':1,
                'startFinish':{'at':s},'sector1End':{'at':a},'sector2End':{'at':b},
                'corners':[{'number':7,'at':a+51.34279017031729/5513},
                           {'number':13,'at':b+80.44643671755874/5513}]}
        checked=fia_check(result)
        self.assertAlmostEqual(checked['checks'][0]['geometryRatioScaledMetres'],1658.6130863187543)
        self.assertEqual([c['fiaMetres'] for c in checked['checks'][:3]],[1658,1941,1914])
        self.assertFalse(any('Sector 1 racing' in x for x in checked['warnings']))
        self.assertTrue(any('Sector 2 racing' in x for x in checked['warnings']))
        self.assertTrue(any('Sector 3 racing' in x for x in checked['warnings']))
        self.assertEqual(checked['accuracyStatus'],'unverified-no-registered-physical-lines')
        self.assertEqual(result['sector1End']['at'],a)

    def test_safe_audit_detects_browser_override_and_fraction_endpoint_mismatch(self):
        points=[[0,0],[100,0],[100,100],[0,100],[0,0]]
        cal={'circuitId':'test','layoutVersion':'v1','geometry':{'points':[{'x':x,'y':y} for x,y in points]}}
        base={'circuitId':'test','layoutVersion':'v1','geometryId':geometry_id(points),'direction':1,'sectorSource':{'year':2026}}
        corners={**base,'corners':[{'number':7,'at':.3,'offset':{'x':1,'y':2}}]}
        sectors={**base,'startFinish':{'at':.996},'sector1End':{'at':.297},'sector2End':{'at':.709}}
        browser={'geometryId':base['geometryId'],'boundaries':[{'key':'sector1End','displayedAt':.347}],
                 'renderedSegments':[{'sector':1,'startAt':0,'endAt':.297,'start':{'x':650,'y':750},'end':{'x':750,'y':731.2}}]}
        result=audit(cal,corners,sectors,browser=browser)
        self.assertIn('override',result['warnings'][0]);self.assertLess(result['renderedEndpointErrors'][0]['endErrorNative'],1e-8)
        self.assertNotIn('positions',result)

    def test_arc_length_is_not_sample_index_and_handles_closed_origin(self):
        p=[[0,0],[1,0],[100,0],[100,100],[0,100],[0,0]]
        np.testing.assert_allclose(arc_point(p,.25),[100,0])
        np.testing.assert_allclose(arc_point(p,1),arc_point(p,0))

    def test_independent_physical_lines_report_and_correct_consistently_biased_estimates(self):
        points=[[0,0],[100,0],[100,100],[0,100],[0,0]]
        result={'circuitId':'test','layoutVersion':'v1','geometryId':geometry_id(points),'direction':1,'sectorSource':{'year':2026},
                'startFinish':{'at':.12,'status':'provisional'},'sector1End':{'at':.35,'status':'provisional'},'sector2End':{'at':.72,'status':'provisional'}}
        reference={'schema':'circuit-physical-timing-lines-v1','circuitId':'test','layoutVersion':'v1','geometryId':geometry_id(points),'season':2026,
                   'provenance':'Independent synthetic surveyed lines','lines':{
                       'startFinish':{'a':[40,-10],'b':[40,10],'uncertaintyNative':1},
                       'sector1End':{'a':[90,20],'b':[110,20],'uncertaintyNative':1},
                       'sector2End':{'a':[20,90],'b':[20,110],'uncertaintyNative':1}}}
        cal={'geometry':{'points':[{'x':x,'y':y} for x,y in points]}}
        fixed=apply_physical_lines(reference,copy.deepcopy(result),cal)
        self.assertEqual([fixed[k]['at'] for k in ('startFinish','sector1End','sector2End')],[.1,.3,.7])
        self.assertEqual(fixed['sector1End']['timingEstimate']['at'],.35)
        self.assertEqual(fixed['sector1End']['status'],'provisional')
        self.assertGreater(fixed['boundaryDiagnostics']['accuracy']['timingMinusPhysicalNative']['sector1End'],10)
        bad=copy.deepcopy(reference);bad['geometryId']='wrong'
        with self.assertRaises(ImportFailure):apply_physical_lines(bad,copy.deepcopy(result),cal)

    def test_low_spread_alone_never_establishes_physical_accuracy(self):
        source,calibration,reference,_=lap_fixture()
        # Shift every car's position phase by the same amount: internally
        # consistent clocks and tiny spread can still produce biased crossings.
        closed=np.vstack([reference,reference[0]])
        for lap in source['boundaryLaps']['laps']:
            for sample in lap['positions']:
                phase=((sample[0]-lap['start'])/100+.145)%1
                sample[1:]=[float(np.interp(phase*256,np.arange(257),closed[:,j])) for j in range(2)]
        output=add_boundaries(source,align(source,calibration,'test','v1'),calibration)
        self.assertLess(output['sector1End']['sourceEstimate']['statistics']['p95LapFraction'],1e-6)
        self.assertEqual(output['boundaryDiagnostics']['accuracy']['status'],'unverified')
        self.assertEqual(output['sector1End']['status'],'provisional')

    def test_python_arc_fraction_matches_frontend_on_nonuniform_closed_path(self):
        import json,shutil,subprocess
        if not shutil.which('node'):self.skipTest('Node not available')
        native=[[0,0],[1,0],[100,0],[100,100],[0,100],[0,0]]
        projected=[[x+650,750-y] for x,y in native]
        script="import {createGeometry,pointAt,pathRange} from './src/circuits/geometry.js';const g=createGeometry("+json.dumps([{'x':x,'y':y} for x,y in native])+ ");console.log(JSON.stringify([.996,.297,.709].map(at=>({point:pointAt(g,at),path:pathRange(g,0,at)}))));"
        rows=json.loads(subprocess.check_output(['node','--input-type=module','-e',script],text=True))
        for at,row in zip((.996,.297,.709),rows):
            expected=arc_point(projected,at)
            np.testing.assert_allclose(expected,[row['point']['x'],row['point']['y']],atol=1e-9)
            end=[float(v) for v in row['path'].split('L')[-1].split()]
            np.testing.assert_allclose(expected,end,atol=1e-9)
