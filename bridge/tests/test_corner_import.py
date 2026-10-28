import math
import tempfile
import unittest
from unittest.mock import patch, Mock

import numpy as np
from bridge.corner_import import normalize, register, project_corner, align, geometry_id, write, fetch


def fixture():
    t=np.arange(256)*2*np.pi/256
    source=np.column_stack([1200*np.cos(t)+220*np.cos(2*t)+120*np.sin(3*t),800*np.sin(t)+70*np.sin(3*t)+90*np.cos(2*t)])
    matrix=np.array([[1.2,.4],[.4,-1.2]])
    target=np.roll(source@matrix+[300,-700],31,axis=0)
    points=np.vstack([target,target[0]])
    corners=normalize([{'Number':i+1,'Letter':'A' if i==1 else '', 'X':source[i*12,0],'Y':source[i*12,1],'Angle':i*18,'Distance':float(i*200)} for i in range(20)])
    data={'schema':'fastf1-circuit-source-v1','year':2026,'event':'synthetic','circuitId':'test','layoutVersion':'v1','rotation':90,'corners':corners,'reference':source.tolist()}
    calibration={'schema':'livef1-circuit-calibration-v1','source':'LiveF1','circuitId':'test','layoutVersion':'v1','geometry':{'points':[{'x':float(x),'y':float(y)} for x,y in points]}}
    return data,calibration,source,points


class CornerImporterTests(unittest.TestCase):
    def test_normalization_letters_and_optional_distance(self):
        out=normalize([{'Number':2,'Letter':'A','X':10,'Y':20,'Angle':45,'Distance':float('nan')},{'Number':2,'Letter':'B','X':12,'Y':21,'Angle':90}])
        self.assertEqual([c['letter'] for c in out],['A','B'])
        self.assertIsNone(out[0]['distance'])
        with self.assertRaises(ValueError):normalize([])
        with self.assertRaises(ValueError):normalize([{'Number':1,'X':float('nan'),'Y':0,'Angle':0}])

    def test_registration_preserves_target_and_imports_twenty_provisional_corners(self):
        data,cal,_,_=fixture()
        original=repr(cal)
        out=align(data,cal,'test','v1')
        self.assertEqual(len(out['corners']),20)
        self.assertTrue(all(c['status']=='provisional' for c in out['corners']))
        self.assertLess(out['alignment']['heldOutP95'],out['alignment']['extent']*.01)
        self.assertEqual(out['corners'][1]['letter'],'A')
        self.assertEqual(out['importSource'],data)
        self.assertEqual(repr(cal),original)
        self.assertIsNone(out['startFinish'])
        self.assertIsNone(out['sector1End'])

    def test_wrong_layout_and_missing_source_fail(self):
        data,cal,_,_=fixture()
        with self.assertRaisesRegex(ValueError,'mismatch'):align(data,cal,'test','other')
        with self.assertRaises(ValueError):align({},cal,'test','v1')

    def test_ambiguous_shape_and_poor_fit_fail(self):
        _,_,src,_=fixture()
        t=np.arange(256)*2*np.pi/256
        circle=np.column_stack([np.cos(t),np.sin(t)])
        with self.assertRaisesRegex(ValueError,'Ambiguous'):register(circle,circle)
        with self.assertRaises(ValueError):register(src,np.column_stack([np.cos(t),np.sin(t)*.1]))

    def test_hairpin_ambiguity_and_far_corner_fail(self):
        track=np.array([[0,0],[1000,0],[1000,10],[0,10],[0,0]],dtype=float)
        with self.assertRaisesRegex(ValueError,'Ambiguous'):project_corner(np.array([500,5]),track,1000)
        with self.assertRaisesRegex(ValueError,'far'):project_corner(np.array([500,1000]),track,1000)

    def test_output_never_overwrites_calibration_or_previous_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=folder+'/file.json';write(path,{'test':1})
            with self.assertRaises(ValueError):write(path,{'test':2})

    def test_missing_fastf1_info_is_explicit(self):
        fake=Mock();fake.get_session.return_value.get_circuit_info.return_value=None
        with tempfile.TemporaryDirectory() as folder,patch.dict('sys.modules',{'fastf1':fake}):
            with self.assertRaisesRegex(ValueError,'no circuit'):fetch(2026,'test','R',folder)

    def test_geometry_fingerprint_stable(self):
        self.assertEqual(geometry_id([[0,0],[10,0],[10,10],[0,0]]),geometry_id([[0,0],[10,0],[10,10],[0,0]]))

    def test_geometry_fingerprint_matches_frontend(self):
        import shutil
        import subprocess
        if not shutil.which('node'):
            self.skipTest('Node unavailable')
        script="import {createGeometry} from './src/circuits/geometry.js';import {geometryId} from './src/circuits/annotations.js';console.log(geometryId(createGeometry([{x:0,y:0},{x:10,y:0},{x:10,y:10},{x:0,y:0}])));"
        actual=subprocess.check_output(['node','--input-type=module','-e',script],text=True).strip()
        self.assertEqual(actual,geometry_id([[0,0],[10,0],[10,10],[0,0]]))
