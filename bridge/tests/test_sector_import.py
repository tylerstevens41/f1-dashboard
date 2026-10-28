import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from bridge.corner_import import ImportFailure, align, project_corner
from bridge.sector_import import add_boundaries, circular_median, collect_laps, crossing_times, interpolate
from bridge.tests.test_corner_import import fixture


def lap_fixture():
    source,calibration,reference,target=fixture()
    laps=[]
    closed=np.vstack([reference,reference[0]])
    for i in range(7):
        start=1000+i*120
        times=start+np.arange(-.4,100.5,.2)
        phase=((times-start)/100+.125)%1
        pos=np.column_stack([np.interp(phase*256,np.arange(257),closed[:,j]) for j in range(2)])
        laps.append({'driver':str(i%3+1),'lap':i+1,'start':start,'end':start+100,'lapTime':100,
                     's1':25,'s2':45,'s3':30,'accurate':True,'pit':False,'generated':False,
                     'trackStatus':'1','clockChecked':True,'positions':np.column_stack([times,pos]).tolist()})
    source['session']='R'
    source['boundaryLaps']={'schema':'fastf1-boundary-laps-v1','laps':laps,'rejected':{},'inspected':7,'timeBasis':'synthetic-session-seconds'}
    return source,calibration,reference,target


class SectorImporterTests(unittest.TestCase):
    def test_interpolation_uses_session_clock_and_surrounding_samples(self):
        point,gap=interpolate([[1000,0,0],[1000.2,10,20]],1000.05)
        np.testing.assert_allclose(point,[2.5,5],atol=1e-8)
        self.assertAlmostEqual(gap,.2)
        with self.assertRaisesRegex(ImportFailure,'unbracketed'):interpolate([[1000,0,0],[1001,1,1]],0)
        with self.assertRaisesRegex(ImportFailure,'gap'):interpolate([[1000,0,0],[1001,1,1]],1000.5)
        with self.assertRaisesRegex(ImportFailure,'nonmonotonic'):interpolate([[1,0,0],[1,2,2]],1)

    def test_missing_pit_inaccurate_and_inconsistent_laps_are_rejected(self):
        source,_,_,_=lap_fixture();lap=source['boundaryLaps']['laps'][0]
        self.assertEqual(crossing_times(lap),[1000,1025,1070,1100])
        for patch in ({'s1':None},{'pit':True},{'accurate':False},{'end':1101},{'s3':31},{'clockChecked':False},{'trackStatus':'4'}):
            with self.assertRaises(ImportFailure):crossing_times({**lap,**patch})

    def test_circular_aggregation_rejects_outlier_across_path_origin(self):
        at,stats=circular_median([.999,.001,0,.0005,.9995,.3])
        self.assertLess(min(at,1-at),.001)
        self.assertEqual(stats['accepted'],5);self.assertEqual(stats['outliers'],1)
        with self.assertRaises(ImportFailure):circular_median([.1,.2])

    def test_multiple_laps_calculate_unequal_boundaries_and_nonzero_finish(self):
        source,calibration,reference,target=lap_fixture()
        result=align(source,calibration,'test','v1')
        matrix=np.array(result['alignment']['matrix']);translation=np.array(result['alignment']['translation'])
        expected=[project_corner(reference[i]@matrix+translation,target,result['alignment']['extent'])[0] for i in (32,96,211)]
        result=add_boundaries(source,result,calibration)
        self.assertEqual(result['boundaryDiagnostics']['validLaps'],7)
        self.assertEqual(result['boundaryDiagnostics']['drivers'],3)
        for key,estimate in zip(('startFinish','sector1End','sector2End'),expected):
            self.assertLess(abs((result[key]['at']-estimate+.5)%1-.5),.002)
            self.assertEqual(result[key]['status'],'provisional')
            self.assertTrue(result[key]['calculated'])
        self.assertGreater(min(result['startFinish']['at'],1-result['startFinish']['at']),.01)
        self.assertEqual(len(result['corners']),20)

    def test_bad_crossings_do_not_poison_valid_laps(self):
        source,calibration,_,_=lap_fixture()
        bad=copy.deepcopy(source['boundaryLaps']['laps'][0]);bad['s1']=None;bad['lap']=998
        source['boundaryLaps']['laps'].append(bad)
        result=add_boundaries(source,align(source,calibration,'test','v1'),calibration)
        self.assertEqual(result['boundaryDiagnostics']['rejected']['missing-timing'],1)
        self.assertEqual(result['boundaryDiagnostics']['validLaps'],7)
        with self.assertRaisesRegex(ImportFailure,'lacks checked'):add_boundaries({},result,calibration)

    def test_cli_exports_all_three_boundaries_from_cached_data(self):
        source,calibration,_,_=lap_fixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);(path/'source.json').write_text(json.dumps(source));(path/'cal.json').write_text(json.dumps(calibration))
            subprocess.run([sys.executable,'-m','bridge.sector_import','--source-input',str(path/'source.json'),'--calibration',str(path/'cal.json'),
                            '--circuit','test','--layout','v1','--output',str(path/'out.json')],check=True,capture_output=True)
            data=json.loads((path/'out.json').read_text())
            self.assertEqual(data['corners'],[])
            self.assertTrue(all(data[k]['calculated'] for k in ('startFinish','sector1End','sector2End')))
            self.assertEqual(json.loads((path/'cal.json').read_text()),calibration)

    def test_collection_checks_date_and_sessiontime_not_sliced_time(self):
        source,_,_,_=lap_fixture();lap=source['boundaryLaps']['laps'][0]
        origin=pd.Timestamp('2026-01-01')
        row={'DriverNumber':'1','LapNumber':1,'LapStartTime':pd.Timedelta(seconds=lap['start']),
             'Time':pd.Timedelta(seconds=lap['end']),'LapTime':pd.Timedelta(seconds=100),
             'Sector1Time':pd.Timedelta(seconds=25),'Sector2Time':pd.Timedelta(seconds=45),'Sector3Time':pd.Timedelta(seconds=30),
             'IsAccurate':True,'PitInTime':pd.NaT,'PitOutTime':pd.NaT,'FastF1Generated':False,'Deleted':False,'TrackStatus':'1',
             'LapStartDate':origin+pd.Timedelta(seconds=lap['start'])}
        p=np.array(lap['positions'])
        pos=pd.DataFrame({'SessionTime':pd.to_timedelta(p[:,0],unit='s'),'Time':pd.to_timedelta(p[:,0]-lap['start'],unit='s'),
                          'Date':origin+pd.to_timedelta(p[:,0],unit='s'),'X':p[:,1],'Y':p[:,2],'Source':'pos','Status':'OnTrack'})
        session=SimpleNamespace(laps=pd.DataFrame([row]),pos_data={'1':pos},t0_date=origin)
        data=collect_laps(session);self.assertEqual(len(data['laps']),1)
        remote=pos[(pos.SessionTime.dt.total_seconds()<lap['start']+40)|(pos.SessionTime.dt.total_seconds()>lap['start']+43)]
        session.pos_data={'1':remote}
        kept=collect_laps(session);self.assertEqual(len(kept['laps']),1);self.assertEqual(kept['laps'][0]['remoteGapCount'],1)
        crossing=pos[(pos.SessionTime.dt.total_seconds()<lap['start']+24)|(pos.SessionTime.dt.total_seconds()>lap['start']+26)]
        session.pos_data={'1':crossing}
        self.assertEqual(collect_laps(session)['rejected']['crossing-gps-gap'],1)
        session.pos_data={'1':pos}
        pos['Date']+=pd.Timedelta(seconds=.01)
        self.assertEqual(collect_laps(session)['rejected']['date-session-clock-mismatch'],1)

    def test_start_end_disagreement_and_crossing_gaps_are_reported(self):
        source,calibration,_,_=lap_fixture()
        bad=copy.deepcopy(source['boundaryLaps']['laps'][0]);bad['end']-=.04;bad['s3']-=.04;bad['lapTime']-=.04
        # A duration-inconsistent lap is excluded rather than changing crossing times.
        bad['s3']+=1
        source['boundaryLaps']['laps'].append(bad)
        gapped=copy.deepcopy(source['boundaryLaps']['laps'][0]);gapped['lap']=997
        gapped['positions']=[p for p in gapped['positions'] if not gapped['start']+24<p[0]<gapped['start']+26]
        source['boundaryLaps']['laps'].append(gapped)
        moved=copy.deepcopy(source['boundaryLaps']['laps'][0]);moved['lap']=999
        for point in moved['positions']:
            if point[0]>moved['end']-.5:point[1:]=source['reference'][64]
        source['boundaryLaps']['laps'].append(moved)
        result=add_boundaries(source,align(source,calibration,'test','v1'),calibration)
        self.assertEqual(result['boundaryDiagnostics']['rejected']['inconsistent-lap-clock'],1)
        self.assertEqual(result['boundaryDiagnostics']['rejected']['lap-start-end-disagreement'],1)
        self.assertEqual(result['boundaryDiagnostics']['rejected']['crossing-gps-gap'],1)

    def test_fia_disagreement_is_flagged_not_adjusted_or_verified(self):
        from bridge.sector_import import fia_check
        source,calibration,_,_=lap_fixture()
        result=add_boundaries(source,align(source,calibration,'test','v1'),calibration)
        result['circuitId']='austin'
        original=[result[k]['at'] for k in ('startFinish','sector1End','sector2End')]
        check=fia_check(result)
        self.assertEqual(check['status'],'discrepancy');self.assertTrue(check['warnings'])
        self.assertEqual(original,[result[k]['at'] for k in ('startFinish','sector1End','sector2End')])
        self.assertTrue(all(result[k]['status']=='provisional' for k in ('startFinish','sector1End','sector2End')))
