"""Season orchestration fixtures, not evidence of real prepared circuits."""
from datetime import datetime,timezone
import copy
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock,patch
from bridge.season_preparation import calendar,inventory,matches,run,session_candidates
from bridge.preparation import AssetStore
from bridge.tests.test_preparation import bundle,annotation

NOW=datetime(2026,11,7,tzinfo=timezone.utc).timestamp()

def catalog_session(name='Mexico City',key=65,year=2026):
    return dict(year=year,event=name+' Grand Prix',location=name,session='Race',start=f'{year}-05-01T12:00:00Z',path=f'{year}/unit-{key}/Race/',circuit={'Key':key,'ShortName':name})


def small_calendar(names=('Mexico City','Suzuka')):
    return dict(schema='season-calendar-v1',year=2026,events=[dict(id=n.lower(),name=n,aliases=[n]) for n in names])


def publish(root,complete=True):
    b=bundle();b['identity']['path']='2026/unit-65/Race/'
    if complete:b.update(corners=annotation(b),sectors=annotation(b),complete=True)
    AssetStore(root).publish(b)
    return b


class SeasonTests(TestCase):
    def test_cached_calendar_is_approved_22_not_claim_of_official_23(self):
        c=calendar(2026)
        self.assertEqual(len(c['events']),22);self.assertTrue(c['sources']);self.assertTrue(c['retrievedAt'])
        self.assertNotIn('Bahrain',[e['name'] for e in c['events']]);self.assertNotIn('Saudi Arabia',[e['name'] for e in c['events']])
        self.assertIn('23',c['discrepancy'])
        japan=next(e for e in c['events'] if e['name']=='Japan')
        self.assertTrue(matches(japan,'Suzuka'));self.assertTrue(matches(japan,'Japanese Grand Prix'))
        austria=next(e for e in c['events'] if e['name']=='Austria');self.assertFalse(matches(austria,'Australian Grand Prix'))

    def test_inventory_skips_valid_and_reports_corruption_without_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            b=publish(temp);before={p:p.read_bytes() for p in Path(temp).rglob('*.json')}
            invalid=Path(temp)/'circuit-99-2026';invalid.mkdir();(invalid/'current.json').write_text('{}')
            records=inventory(temp,Path(temp)/'public',2026)
            self.assertEqual(sum(r['integrity']=='valid' for r in records),1)
            self.assertEqual(sum(r['integrity']=='invalid' for r in records),1)
            for p,data in before.items():self.assertEqual(p.read_bytes(),data)

    def test_dry_run_has_no_downloads_or_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'absent';fetch=Mock(side_effect=AssertionError('network'))
            result=run(2026,root,Path(temp)/'public',dry_run=True,lister=fetch,emit=lambda _:None)
            self.assertEqual(result['summary']['total'],22);fetch.assert_not_called();self.assertFalse(root.exists())

    def test_existing_complete_assets_are_idempotently_skipped(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.season_preparation.calendar',return_value=small_calendar(('Mexico City',))):
            publish(temp);fetch=Mock();prep=Mock()
            for _ in range(2):
                report=run(2026,temp,Path(temp)/'public',lister=fetch,preparer=prep,now=NOW,emit=lambda _:None)
                self.assertEqual(report['summary']['already-prepared'],1)
            fetch.assert_not_called();prep.assert_not_called()

    def test_partial_resumes_existing_source_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.season_preparation.calendar',return_value=small_calendar()):
            partial=publish(temp,False)
            sessions=[catalog_session(),catalog_session('Suzuka',13)]
            seen=[]
            def prep(session,store,report):
                seen.append(session['path'])
                if '13' in session['path']:raise ValueError('SECRET upstream message')
                b=copy.deepcopy(partial);b.update(corners=annotation(b),sectors=annotation(b),complete=True);store.publish(b);return b
            result=run(2026,temp,Path(temp)/'public',lister=lambda _:sessions,preparer=prep,now=NOW,emit=lambda _:None)
            self.assertEqual(result['summary']['newly-prepared'],1);self.assertEqual(result['summary']['failed'],1)
            self.assertEqual(len(seen),2);self.assertNotIn('SECRET',str(result))
            again=run(2026,temp,Path(temp)/'public',lister=lambda _:sessions,preparer=Mock(side_effect=AssertionError('backoff')),now=NOW+10,emit=lambda _:None)
            self.assertEqual(again['summary']['already-prepared'],1);self.assertEqual(again['summary']['skipped'],1)

    def test_earlier_season_discovery_does_not_assume_layout_compatibility(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.season_preparation.calendar',return_value=small_calendar(('Suzuka',))):
            prep=Mock();result=run(2026,temp,Path(temp)/'public',lister=lambda y:[catalog_session('Suzuka',13,y)] if y==2025 else [],preparer=prep,now=NOW,emit=lambda _:None)
            self.assertEqual(result['queue'][0]['reason'],'older-source-found-layout-compatibility-unverified')
            self.assertEqual(result['queue'][0]['fallbackCandidates'][0]['year'],2025);prep.assert_not_called()

    def test_session_selection_uses_real_venue_identity_and_completed_time(self):
        event={'aliases':['Madrid']}
        s=catalog_session('Madrid',999);s['event']='Spanish Grand Prix'
        old={**catalog_session('Barcelona',99),'event':'Spanish Grand Prix'}
        future={**s,'start':'2026-12-01T12:00:00Z'}
        self.assertEqual(session_candidates(event,[old,s,future],2026,NOW),[s])

    def test_authentication_failure_classified_once_and_batch_finishes(self):
        class AuthError(Exception):code='authentication-required'
        with tempfile.TemporaryDirectory() as temp,patch('bridge.season_preparation.calendar',return_value=small_calendar()):
            fetch=Mock(side_effect=AuthError('SECRET'))
            report=run(2026,temp,Path(temp)/'public',lister=fetch,now=NOW,emit=lambda _:None)
            self.assertEqual(fetch.call_count,1);self.assertEqual(report['summary']['failed'],2)
            self.assertTrue(all(r['failureCategory']=='authentication' for r in report['queue']));self.assertNotIn('SECRET',str(report))

    def test_public_austin_and_dynamic_mexico_suzuka_are_preserved(self):
        from bridge.preparation import identity
        from bridge.tests.test_preparation import calibration,session
        from bridge.corner_import import geometry_id
        import json
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'store';public=Path(temp)/'public';public.mkdir()
            publish(root)
            meta=identity(session(13,'Suzuka'));cal=calibration(meta)
            b=bundle();b.update(identity=meta,calibration=cal,geometryId=geometry_id([[p['x'],p['y']] for p in cal['geometry']['points']]))
            b.update(corners=annotation(b),sectors=annotation(b),complete=True);AssetStore(root).publish(b)
            meta=identity(session(63,'Austin'));cal=calibration(meta);cal['provenance']['sessionPaths']=['2026/unit/Race/']
            b.update(identity=meta,calibration=cal,geometryId=geometry_id([[p['x'],p['y']] for p in cal['geometry']['points']]))
            (public/'austin-calibration.json').write_text(json.dumps(cal))
            for name in ('corners','sectors'):(public/f'austin-{name}.json').write_text(json.dumps(annotation(b)))
            before={p:p.read_bytes() for p in public.glob('*.json')}
            with patch('bridge.season_preparation.calendar',return_value=small_calendar(('Austin','Mexico City','Suzuka'))):
                fetch=Mock();prep=Mock()
                result=run(2026,root,public,lister=fetch,preparer=prep,now=NOW,emit=lambda _:None)
            self.assertEqual(result['summary']['already-prepared'],3);prep.assert_not_called();fetch.assert_not_called()
            for p,data in before.items():self.assertEqual(p.read_bytes(),data)

    def test_interruption_resumes_queue_using_persisted_asset_checkpoints(self):
        import json
        with tempfile.TemporaryDirectory() as temp,patch('bridge.season_preparation.calendar',return_value=small_calendar(('Mexico City',))):
            directory=Path(temp)/'season-2026';directory.mkdir()
            (directory/'report.json').write_text(json.dumps({'queue':[{'eventId':'mexico city','status':'preparing','attempts':1}]}))
            b=publish(temp,False)
            def prep(*args,**kwargs):
                b.update(corners=annotation(b),sectors=annotation(b),complete=True);kwargs['store'].publish(b);return b
            result=run(2026,temp,Path(temp)/'public',lister=lambda _:[catalog_session()],preparer=prep,now=NOW,emit=lambda _:None)
            self.assertEqual(result['queue'][0]['attempts'],2);self.assertEqual(result['summary']['newly-prepared'],1)

    def test_first_circuit_failure_does_not_prevent_next_missing_circuit(self):
        with tempfile.TemporaryDirectory() as temp,patch('bridge.season_preparation.calendar',return_value=small_calendar(('Suzuka','Mexico City'))):
            seen=[]
            def prep(session,store,report):
                seen.append(session['location'])
                if session['location']=='Suzuka':raise ValueError('private error')
                b=bundle();b.update(corners=annotation(b),sectors=annotation(b),complete=True);store.publish(b);return b
            report=run(2026,temp,Path(temp)/'public',lister=lambda y:[catalog_session('Suzuka',13),catalog_session()] if y==2026 else [],preparer=prep,now=NOW,emit=lambda _:None)
            self.assertEqual(seen,['Suzuka','Mexico City']);self.assertEqual(report['summary']['failed'],1);self.assertEqual(report['summary']['newly-prepared'],1)
