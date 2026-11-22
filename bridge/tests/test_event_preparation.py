"""Synthetic event preparation fixtures; no real Vegas geometry/accuracy evidence."""
from datetime import datetime,timezone
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock

from bridge.archive import ArchiveUnavailable
from bridge.event_preparation import candidates,run
from bridge.preparation import AssetStore,PreparationError,identity,prepare
from bridge.tests.test_preparation import calibration,annotation

NOW=datetime(2026,11,22,2,tzinfo=timezone.utc).timestamp()
def source(kind='Qualifying',start='2026-11-20T20:00:00-08:00',year=2026):
    return {'year':year,'event':'Las Vegas Grand Prix','location':'Las Vegas','session':kind,
            'path':f'{year}/fixture-vegas/{kind}/','start':start,'circuit':{'Key':999,'ShortName':'Las Vegas'}}


class EventTests(TestCase):
    def test_current_qualifying_practice_without_future_race_or_older_layout(self):
        q=source();p=source('Practice 2','2026-11-19T20:00:00-08:00')
        race=source('Race','2026-11-21T20:00:00-08:00');old=source(year=2025)
        self.assertEqual(candidates([old,p,race,q,q],2026,'Las Vegas',NOW),[q,p])
        self.assertEqual(candidates([old,race],2026,'Las Vegas',NOW),[])

    def test_timezone_unknown_identity_ambiguity_and_path_season_fail_closed(self):
        naive={**source(),'start':'2026-11-20T20:00:00'}
        self.assertEqual(candidates([naive],2026,'Las Vegas',NOW),[])
        self.assertEqual(candidates([{**naive,'gmtOffset':'-08:00:00'}],2026,'Las Vegas',NOW)[0]['session'],'Qualifying')
        self.assertEqual(candidates([{**source(),'path':'2025/fixture/'}],2026,'Las Vegas',NOW),[])
        other={**source('Practice 1'),'circuit':{'Key':998,'ShortName':'Las Vegas'}}
        with self.assertRaises(PreparationError):candidates([source(),other],2026,'Las Vegas',NOW)

    def test_measured_windows_shared_geometry_checks_and_independent_annotations(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root);scan=Mock(return_value=1234)
            collect=Mock(side_effect=lambda meta,*a,**k:calibration(meta));imports=Mock(side_effect=AssertionError('geometry only'))
            result=run(2026,'Las Vegas',store,geometry_only=True,lister=lambda _:[source()],scanner=scan,collector=collect,importer=imports,now=NOW)
            self.assertEqual(result['status'],'geometry-ready');scan.assert_called_once();imports.assert_not_called()
            self.assertEqual(collect.call_args.kwargs['windows'],(1234,))
            meta=identity(source());before=store.get(meta);fingerprint=before['geometryId']
            # Repeat does not even rewrite a valid geometry pointer.
            pointer=store.directory(meta['assetKey'])/'current.json';old=pointer.read_bytes()
            repeat=run(2026,'Las Vegas',store,geometry_only=True,lister=lambda _:[source()],scanner=Mock(side_effect=AssertionError('rescan')),collector=Mock(),now=NOW)
            self.assertEqual(repeat['status'],'geometry-ready');self.assertEqual(pointer.read_bytes(),old)
            def importer(meta,cal,root,progress):
                b=store.get(meta);return annotation(b),annotation(b),[]
            result=run(2026,'Las Vegas',store,annotations_only=True,lister=lambda _:[source()],scanner=Mock(side_effect=AssertionError('rescan')),importer=importer,now=NOW)
            self.assertEqual(result['status'],'complete');self.assertEqual(store.get(meta)['geometryId'],fingerprint)
            self.assertEqual(store.get(meta)['calibration'],before['calibration'])

    def test_unavailable_historical_data_does_not_create_geometry(self):
        with tempfile.TemporaryDirectory() as root:
            scan=Mock();r=run(2026,'Las Vegas',AssetStore(root),lister=lambda _:[source(year=2025)],scanner=scan,now=NOW)
            self.assertEqual(r['status'],'unavailable');scan.assert_not_called()
            self.assertFalse(list(Path(root).glob('circuit-*/current.json')))

    def test_fallback_to_next_same_season_archive_after_scan_failure(self):
        with tempfile.TemporaryDirectory() as root:
            q=source();p=source('Practice 2','2026-11-19T20:00:00-08:00')
            scan=Mock(side_effect=[ValueError('PRIVATE TOKEN'),1000]);collect=Mock(side_effect=lambda meta,*a,**k:calibration(meta))
            r=run(2026,'Las Vegas',AssetStore(root),geometry_only=True,lister=lambda _:[q,p],scanner=scan,collector=collect,now=NOW)
            self.assertEqual(r['status'],'geometry-ready');self.assertEqual(r['selectedSession']['session'],'Practice 2')
            self.assertNotIn('PRIVATE TOKEN',str(r));self.assertEqual(len(r['attempts']),2)

    def test_authentication_failure_is_sanitized_and_never_triggers_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            q=source();p=source('Practice 2','2026-11-19T20:00:00-08:00')
            scan=Mock(side_effect=ArchiveUnavailable('PRIVATE TOKEN',code='authentication-required'))
            r=run(2026,'Las Vegas',AssetStore(root),geometry_only=True,lister=lambda _:[q,p],scanner=scan,now=NOW)
            self.assertEqual(r['status'],'failed');self.assertEqual(scan.call_count,1)
            self.assertEqual(r['attempts'][0]['error']['code'],'authentication-required');self.assertNotIn('PRIVATE TOKEN',str(r))

    def test_annotation_failure_keeps_geometry_and_does_not_try_another_source(self):
        with tempfile.TemporaryDirectory() as root:
            collect=Mock(side_effect=lambda meta,*a,**k:calibration(meta))
            r=run(2026,'Las Vegas',AssetStore(root),lister=lambda _:[source(),source('Practice 2','2026-11-19T20:00:00-08:00')],scanner=Mock(return_value=1000),collector=collect,importer=Mock(side_effect=RuntimeError('PRIVATE')),now=NOW)
            self.assertEqual(r['status'],'geometry-ready');self.assertEqual(collect.call_count,1)
            self.assertEqual(r['audit']['annotations']['corners'],0)

    def test_stages_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PreparationError):run(2026,'Las Vegas',AssetStore(root),geometry_only=True,annotations_only=True)
            with self.assertRaises(PreparationError):prepare(source(),AssetStore(root),geometry_only=True,annotations_only=True)

    def test_qualifying_geometry_is_resolvable_for_race_by_provider_circuit_key(self):
        with tempfile.TemporaryDirectory() as root:
            store=AssetStore(root)
            run(2026,'Las Vegas',store,geometry_only=True,lister=lambda _:[source()],scanner=Mock(return_value=1000),collector=lambda meta,*a,**k:calibration(meta),now=NOW)
            bundle=store.lookup(2026,circuit_key=999)
            self.assertEqual(bundle['identity']['session'],'Qualifying')
            self.assertIsNone(store.lookup(2025,circuit_key=999))
            self.assertIsNone(store.lookup(2026,circuit_key=998))
