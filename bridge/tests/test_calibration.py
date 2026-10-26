"""All generated trajectories here are synthetic unit fixtures, not Austin evidence."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from bridge.calibration_math import register_svg, sample_svg
from bridge.calibrate import build, clean_laps, read_json, validate, write_json


def dataset():
    samples=[]
    for lap in range(1,7):
        for i,angle in enumerate(np.linspace(0,2*np.pi,181)):
            samples.append({'driver':str(1+lap%2),'lap':lap,'time':lap*100000+i*500,'frameTime':lap*100000+i*500,
                            'x':100+50*np.cos(angle),'y':200+30*np.sin(angle),'status':'OnTrack','inPit':False,'pitOut':False})
    return {'schema':'livef1-calibration-samples-v1','source':'LiveF1','synthetic':True,'circuitId':'unit','sessionPath':'synthetic-unit-only','samples':samples}


class CalibrationTests(unittest.TestCase):
    def test_transform_fit_reflection_rotation_translation(self):
        angle=np.linspace(0,2*np.pi,160,endpoint=False)
        source=np.c_[np.cos(angle)*(1+0.2*np.cos(3*angle)),0.6*np.sin(angle)]
        theta=0.4;rotation=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
        target=(source*np.array([1,-1]))@rotation.T*100+np.array([500,800])
        fit=register_svg(source,target)
        self.assertLess(fit['similarity']['trajectoryToOutline']['p95FractionOfDiagonal'],0.01)
        self.assertAlmostEqual(fit['similarity']['scaleRatio'],1,places=5)
        self.assertTrue(fit['similarity']['reflected'])

    def test_cleaning_rejects_pit_stale_invalid_and_partial(self):
        data=dataset();data['samples'][0]['x']=float('nan');data['samples'][200]['frameTime']-=10000
        for row in data['samples']:
            if row['lap']==3:row['inPit']=True
        data['samples'].append({'driver':'x','lap':7,'time':1,'frameTime':1,'x':10,'y':10,'status':'OffTrack'})
        laps,reasons=clean_laps(data)
        self.assertGreaterEqual(len(laps),3)
        for key in ('invalid','stale','offTrack','pitLaps'):self.assertGreater(reasons[key],0)
        self.assertFalse(any(lap['id'].endswith('|3') for lap in laps))

    def test_persistence_holdout_and_no_synthetic_verification(self):
        data=dataset()
        with tempfile.TemporaryDirectory() as directory:
            svg=Path(directory)/'ellipse.svg'
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(10 20)"><path id="track" d="M 50 0 A 50 30 0 1 1 -50 0 A 50 30 0 1 1 50 0 Z"/></g></svg>')
            calibration=build(data,svg,layout='unit-v1')
            self.assertEqual(calibration['status'],'candidate')
            self.assertTrue(calibration['validation']['automaticChecksPassed'])
            self.assertFalse(set(calibration['validation']['trainingLapIds']) & set(calibration['validation']['heldOutLapIds']))
            path=Path(directory)/'candidate.json'
            write_json(path,calibration)
            restored=read_json(path)
            self.assertEqual(restored['mapping']['matrix'],[1,0,0,1,0,0])
            self.assertEqual(restored['geometry']['points'][0],restored['geometry']['points'][-1])
            validate(restored,data,True,True)
            self.assertEqual(restored['status'],'candidate')
            self.assertFalse(restored['validation']['verified'])

    def test_partial_data_cannot_replace_geometry(self):
        data=dataset();data['samples']=data['samples'][:40]
        with self.assertRaises(ValueError):build(data,'does-not-matter.svg')

    def test_svg_parent_transforms_and_open_path_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'track.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(10,20)"><path id="track" d="M0 0 L10 0 L10 10 L0 10 Z"/></g></svg>')
            points,_=sample_svg(path,'track',16)
            self.assertAlmostEqual(points[:,0].min(),10)
            self.assertAlmostEqual(points[:,1].max(),30)
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>')
            with self.assertRaises(ValueError):sample_svg(path)


if __name__=='__main__':unittest.main()
