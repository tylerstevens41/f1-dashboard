"""Synthetic regressions; no evidence about real Mexico telemetry quality."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge.archive import ArchiveUnavailable
from bridge.calibrate import build, clean_laps, collect_clip
from bridge.preparation import collect_geometry, PreparationError, AssetStore
from bridge.tests.test_calibration import dataset
from bridge.tests.test_preparation import identity, session


class GeometryDiagnosticTests(unittest.TestCase):
    def exercise(self, *, fetch=None, extract=None, build_result=None, build_error=None, cached=None):
        # Keep temporary context alive until diagnostic JSON is read.
        with tempfile.TemporaryDirectory() as root:
            meta=identity(session());cache=Path(root)/'gps-cache';cache.mkdir()
            clip={'synthetic':True,'originMs':0,'clockBasis':'gps-utc','initial':{'SessionInfo':{'Meeting':{'Circuit':{'Key':65}}}},
                  'events':[{'topic':'Position.z','offsetMs':0,'payload':'fixture'}], 'capabilities':{'Position.z':'available'}}
            data=copy.deepcopy(extract if isinstance(extract,dict) else dataset())
            data.update(circuitId=meta['id'],sessionPath=meta['path'],sessionPaths=[meta['path']])
            if cached is not None:
                from bridge.calibrate import write_json
                token=hashlib.sha256(f"{meta['path']}:1:480:extraction-v2".encode()).hexdigest()
                write_json(cache/f'{token}.json.gz',cached)
            def collector(clip, diagnostics=None):
                if isinstance(extract,Exception):raise extract
                samples=data.get('samples',[])
                if diagnostics is not None:diagnostics.update(decodedPositionRecords=len(samples),positionMessages=1,acceptedPositionRecords=len(samples))
                return samples
            output=None
            def actual_build(*a,**k):return build(*a,**k)
            with patch('bridge.archive.fetch_clip',side_effect=fetch if isinstance(fetch,Exception) else None,return_value=fetch if isinstance(fetch,dict) else clip),patch('bridge.calibrate.collect_clip',side_effect=collector),patch('bridge.calibrate.build',side_effect=build_error or (lambda *a,**k:build_result if build_result is not None else actual_build(*a,**k))):
                try:
                    output=collect_geometry(meta,cache,lambda **_:None,windows=(1,))
                except PreparationError:
                    pass
            diagnostics=json.loads((Path(root)/meta['assetKey']/'geometry-diagnostics.json').read_text())
            return diagnostics['windows'][0],output

    def test_archive_failure_is_not_reported_as_insufficient_laps_and_secret_is_absent(self):
        d,out=self.exercise(fetch=ArchiveUnavailable('Bearer SECRET_TOKEN https://private.example?token=SECRET_TOKEN',code='authentication-required'))
        self.assertIsNone(out);self.assertEqual(d['stage'],'archive');self.assertFalse(d['archiveRetrieved'])
        self.assertEqual(d['error']['exceptionType'],'ArchiveUnavailable');self.assertEqual(d['error']['code'],'authentication-required')
        self.assertNotIn('SECRET_TOKEN',json.dumps(d));self.assertIsNone(d['candidateLaps'])

    def test_missing_positions_are_distinct_from_retrieval_failure(self):
        data=dataset();data['samples']=[]
        d,_=self.exercise(extract=data)
        self.assertTrue(d['archiveRetrieved']);self.assertEqual(d['reason'],'no-position-samples')
        self.assertEqual(d['sampleCount'],0);self.assertEqual(d['candidateLaps'],0)
        self.assertFalse(d['calibrationAttempted'])

    def test_unexpected_archive_and_decoder_schema_have_stage_and_exception_category(self):
        d,_=self.exercise(fetch={'events':'unexpected'})
        self.assertEqual(d['stage'],'archive');self.assertEqual(d['error']['exceptionType'],'PreparationError')
        d,_=self.exercise(extract=KeyError('secret authentication response'))
        self.assertEqual(d['stage'],'extract');self.assertEqual(d['error']['exceptionType'],'KeyError')
        self.assertNotIn('secret authentication',json.dumps(d))

    def test_incomplete_laps_include_specific_rejection_reasons_without_relaxing_checks(self):
        data=dataset();data['samples']=data['samples'][:35]
        d,_=self.exercise(extract=data)
        self.assertEqual(d['reason'],'insufficient-complete-laps');self.assertEqual(d['candidateLaps'],1)
        self.assertEqual(d['acceptedCompleteLaps'],0);self.assertEqual(d['incompleteLapReasons']['tooFewSamples'],1)
        self.assertEqual(d['rejected']['incompleteLaps'],1)

    def test_cleaning_explains_remote_gap_and_open_loop_rejections(self):
        data=dataset()
        data['samples']=[p for p in data['samples'] if not (p['lap']==1 and 110000<p['time']<120000)]
        stats={};laps,_=clean_laps(data,stats)
        self.assertEqual(stats['candidateLaps'],6);self.assertEqual(stats['incompleteLapReasons']['gpsGap'],1)
        self.assertEqual(len(laps),5)
        self.assertIn('lap groups',stats['rejectionUnits']['pitLaps/incompleteLaps'])

    def test_failed_calibration_records_metrics_and_unexpected_error_is_safe(self):
        result=build(dataset(),layout=identity(session())['layoutVersion'])
        result['validation']['automaticChecksPassed']=False
        d,_=self.exercise(build_result=result)
        self.assertTrue(d['calibrationAttempted']);self.assertEqual(d['reason'],'held-out-geometry-error')
        self.assertFalse(d['calibration']['automaticChecksPassed']);self.assertIn('heldOut',d['calibration'])
        d,_=self.exercise(build_error=RuntimeError('password=SECRET_TOKEN'))
        self.assertEqual(d['stage'],'build');self.assertEqual(d['error']['exceptionType'],'RuntimeError')
        self.assertNotIn('SECRET_TOKEN',json.dumps(d));self.assertTrue(d['calibrationAttempted'])

    def test_successful_fixture_has_full_collection_cleaning_and_validation_diagnostics(self):
        d,out=self.exercise()
        self.assertIsNotNone(out);self.assertEqual(d['status'],'accepted');self.assertEqual(d['acceptedCompleteLaps'],6)
        self.assertEqual(d['driversRepresented'],2);self.assertGreater(d['decodedPositionRecords'],1000)
        self.assertTrue(d['calibration']['automaticChecksPassed']);self.assertTrue(out['provenance']['synthetic'])
        self.assertEqual(out['validation']['preparationDiagnostics']['windows'][0]['status'],'accepted')

    def test_failed_job_retains_window_report_when_final_status_is_written(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root);meta=identity(session())
            store.progress(meta,state='preparing',windowDiagnostics=[{'offset':1,'stage':'extract'}])
            failed=store.progress(meta,state='failed',error='safe summary')
            self.assertEqual(failed['windowDiagnostics'][0]['stage'],'extract')

    def test_collector_preserves_batched_samples_and_ignores_unrelated_broken_telemetry(self):
        import livef1.data_processing.etl as etl
        base='2026-11-01T20:00:00.'
        records=[{'DriverNo':'1','Utc':base+suffix+'Z','X':10,'Y':20,'Status':'OnTrack'} for suffix in ('200','000','100')]
        clip={'originMs':1793563200000,'initial':{'TimingData':{'1':{'NumberOfLaps':3}}},'events':[
            {'topic':'CarData.z','offsetMs':0,'payload':'malformed unrelated compressed telemetry'},
            {'topic':'Position.z','offsetMs':0,'payload':'fixture'}]}
        def bad_car(*a,**k):raise AssertionError('Unrelated decoder must not run')
        with patch.dict(etl.function_map,{'Position.z':lambda *a,**k:iter(records),'CarData.z':bad_car}):
            stats={};samples=collect_clip(clip,stats)
        self.assertEqual(len(samples),3);self.assertEqual([p['lap'] for p in samples],[3]*3)
        self.assertEqual(stats['duplicateOrOlderRecords'],0);self.assertEqual(stats['ignoredMessages'],1)
        self.assertEqual(sorted(p['time'] for p in samples),[p['time'] for p in samples])

    def test_observed_no_events_gap_schedules_bounded_measured_window_then_succeeds(self):
        meta=identity(session());calls=[]
        def retrieve(path,offset,duration,**options):
            calls.append(offset)
            if offset==5400:
                options['diagnostics'].update(archiveFirstOffsetSeconds={'Position.z':616.289},
                    archiveFirstAfterWindowSeconds={'Position.z':90000},archiveLastOffsetSeconds={'Position.z':90000})
                raise ArchiveUnavailable('No events',code='no-events')
            return {'synthetic':True,'originMs':0,'initial':{'SessionInfo':{'Meeting':{'Circuit':{'Key':65}}}},'events':[]}
        with tempfile.TemporaryDirectory() as root,patch('bridge.archive.fetch_clip',side_effect=retrieve),patch('bridge.calibrate.collect_clip',return_value=dataset()['samples']):
            result=collect_geometry(meta,Path(root)/'gps-cache',lambda **_:None,windows=(5400,))
            report=json.loads((Path(root)/meta['assetKey']/'geometry-diagnostics.json').read_text())
        self.assertEqual(calls,[5400,90000]);self.assertTrue(result['provenance']['synthetic'])
        self.assertEqual(report['windows'][1]['windowSource'],'observed-gps-after-requested-window')
        self.assertEqual(result['provenance']['preparationWindowSeconds'],90000)

    def test_discovery_never_guesses_without_measured_coverage_and_has_retry_limit(self):
        meta=identity(session());calls=[]
        def retrieve(path,offset,duration,**options):
            calls.append(offset)
            options['diagnostics'].update(archiveFirstAfterWindowSeconds={'Position.z':offset+10000})
            raise ArchiveUnavailable('No events',code='no-events')
        with tempfile.TemporaryDirectory() as root,patch('bridge.archive.fetch_clip',side_effect=retrieve):
            with self.assertRaises(PreparationError):collect_geometry(meta,Path(root)/'gps-cache',lambda **_:None,windows=(5400,))
        self.assertEqual(calls,[5400,15400,25400])

    def test_decoder_missing_timestamps_and_unexpected_records_are_counted_or_categorized(self):
        import livef1.data_processing.etl as etl
        clip={'originMs':0,'initial':{},'events':[{'topic':'Position.z','offsetMs':0,'payload':'fixture'}]}
        with patch.dict(etl.function_map,{'Position.z':lambda *a,**k:iter([{'DriverNo':'1','X':1,'Y':2}])}):
            stats={};self.assertEqual(collect_clip(clip,stats),[])
        self.assertEqual(stats['invalidTimestamps'],1);self.assertEqual(stats['decodedPositionRecords'],1)
        with patch.dict(etl.function_map,{'Position.z':lambda *a,**k:iter([{'unexpected':'private record'}])}):
            with self.assertRaises(ValueError) as context:collect_clip(clip,{})
        from bridge.diagnostics import safe_exception
        detail=safe_exception(context.exception,'extract')
        self.assertEqual(detail['code'],'invalid-position-record-schema')
        self.assertNotIn('private record',json.dumps(detail))

    def test_real_decoder_compressed_payload_and_missing_timestamp_diagnostics(self):
        import base64,zlib
        from bridge.protocol import utc_ms
        payload={'Position':[{'Timestamp':'2026-11-01T20:00:00.000Z','Entries':{'1':{'X':100,'Y':200,'Status':'OnTrack'}}}]}
        raw=zlib.compress(json.dumps(payload).encode())[2:-4]
        clip={'originMs':utc_ms('2026-11-01T20:00:00Z'),'initial':{'TimingData':{'1':{'NumberOfLaps':3}}},'events':[
            {'topic':'Position.z','offsetMs':0,'payload':base64.b64encode(raw).decode()}]}
        stats={};samples=collect_clip(clip,stats)
        self.assertEqual(len(samples),1);self.assertEqual(samples[0]['lap'],3)
        self.assertEqual(stats['driversRepresented'],1)
        with self.assertRaisesRegex(ValueError,'schema'):collect_clip({'initial':{},'events':'wrong','originMs':0})
