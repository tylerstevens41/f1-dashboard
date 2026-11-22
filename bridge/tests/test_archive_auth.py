"""Synthetic credentials/HTTP responses only. Never use local account contents."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from bridge.archive import response,ArchiveUnavailable,request_diagnostics
from bridge.archive_auth import headers
from bridge.diagnostics import safe_exception


def reply(status,headers=None):return SimpleNamespace(status_code=status,ok=status<400,headers=headers or {},close=Mock())


class AuthTests(TestCase):
    def setUp(self):
        p=patch('bridge.archive_auth._LAST_REFRESH',0);p.start();self.addCleanup(p.stop)
        p=patch('livef1.auth._read_env',return_value={});self.env=p.start();self.addCleanup(p.stop)
        p=patch('livef1.auth._env_path',return_value=Path('SYNTHETIC_ENV'));p.start();self.addCleanup(p.stop)
        p=patch.dict('os.environ',{},clear=True);p.start();self.addCleanup(p.stop)

    def test_shared_live_token_is_reused_without_login_or_prompt(self):
        with patch('livef1.auth.auth_header',return_value={'Authorization':'Bearer SYNTHETIC'}),patch('livef1.auth.login') as login:
            self.assertEqual(headers(),({'Authorization':'Bearer SYNTHETIC'},False));login.assert_not_called()

    def test_expired_missing_token_renews_with_explicit_sdk_credentials(self):
        self.env.return_value={'F1_USERNAME':'SYNTHETIC_USER','F1_PASSWORD':'SYNTHETIC_PASSWORD'}
        with patch('livef1.auth.auth_header',return_value={}),patch('livef1.auth.login',return_value=SimpleNamespace(header={'Authorization':'Bearer NEW_SYNTHETIC'})) as login:
            auth,attempted=headers();self.assertTrue(attempted);self.assertIn('Authorization',auth)
            login.assert_called_once_with(username='SYNTHETIC_USER',password='SYNTHETIC_PASSWORD',force=False)
            headers();self.assertEqual(login.call_count,1) # Global cooldown; no prompt loop.

    def test_missing_credentials_never_prompt_in_controller(self):
        with patch('livef1.auth.auth_header',return_value={}),patch('livef1.auth.login') as login:
            self.assertEqual(headers(),({},False));login.assert_not_called()

    def test_changed_shared_token_is_reused_instead_of_forced_signin(self):
        with patch('livef1.auth.auth_header',return_value={'Authorization':'Bearer NEW'}),patch('livef1.auth.login') as login:
            self.assertEqual(headers(force=True,rejected={'Authorization':'Bearer OLD'}),({'Authorization':'Bearer NEW'},False));login.assert_not_called()

    def test_metadata_401_refreshes_once_and_never_exports_credentials(self):
        denied=reply(401);allowed=reply(200,{'Age':'0','X-Cache':'Miss from edge','Date':'Sun, 22 Nov 2026 04:00:00 GMT'})
        report={}
        with patch('bridge.archive_auth.headers',side_effect=[({'Authorization':'Bearer OLD_SECRET'},False),({'Authorization':'Bearer NEW_SECRET'},True)]),patch('bridge.archive.requests.get',side_effect=[denied,allowed]) as get:
            with request_diagnostics(report):self.assertIs(response('2026/Index.json'),allowed)
            self.assertEqual(get.call_count,2);denied.close.assert_called_once()
            self.assertEqual(get.call_args.kwargs['headers']['User-Agent'],'BestHTTP')
            self.assertIn('_f1dash',get.call_args.kwargs['params'])
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertNotIn('SECRET',str(report));self.assertTrue(report['requests'][0]['refreshSucceeded'])

    def test_authorized_403_is_access_denial_not_missing_login_or_bypass(self):
        report={}
        with patch('bridge.archive_auth.headers',return_value=({'Authorization':'Bearer SYNTHETIC_SECRET'},False)) as auth,patch('bridge.archive.requests.get',return_value=reply(403)):
            with request_diagnostics(report):
                with self.assertRaises(ArchiveUnavailable) as error:response('2026/fixture/Index.json')
            self.assertEqual(error.exception.code,'archive-access-denied');auth.assert_called_once()
            safe=safe_exception(error.exception,'archive');self.assertEqual(safe['httpStatus'],403)
            self.assertNotIn('SYNTHETIC_SECRET',str(safe)+str(report))
            self.assertTrue(report['requests'][0]['attempts'][0]['authorizationSent'])

    def test_unauthenticated_403_still_requires_login_without_unbounded_retries(self):
        with patch('bridge.archive_auth.headers',return_value=({},False)),patch('bridge.archive.requests.get',return_value=reply(403)) as get:
            with self.assertRaises(ArchiveUnavailable) as error:response('2026/fixture/Index.json')
            self.assertEqual(error.exception.code,'authentication-required');self.assertEqual(get.call_count,1)

    def test_rejected_refreshed_token_stops_after_two_requests(self):
        with patch('bridge.archive_auth.headers',side_effect=[({'Authorization':'Bearer OLD'},False),({'Authorization':'Bearer NEW'},True)]),patch('bridge.archive.requests.get',side_effect=[reply(401),reply(401)]) as get:
            with self.assertRaises(ArchiveUnavailable) as error:response('2026/fixture/Index.json')
            self.assertEqual(error.exception.code,'authentication-required');self.assertEqual(get.call_count,2)

    def test_year_index_counts_reveal_path_filter_without_local_cache(self):
        from bridge.archive import list_sessions
        report={}
        value={'Meetings':[{'Key':1,'Name':'Synthetic event','Sessions':[
            {'Key':2,'Name':'Qualifying','Path':'2026/fixture/Qualifying/'},
            {'Key':3,'Name':'Race','Path':None}]}]}
        with patch('bridge.archive.small_json',return_value=value):
            with request_diagnostics(report):sessions=list_sessions(2026)
        self.assertEqual(len(sessions),1);self.assertEqual(report['rawSessionEntries'],2)
        self.assertEqual(report['entriesWithoutPath'],1);self.assertFalse(report['localCacheUsed'])
