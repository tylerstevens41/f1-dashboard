import unittest
from types import SimpleNamespace
from unittest.mock import patch
import requests
from bridge.fastf1_network import bounded_network,endpoint,FastF1AuthenticationRequired
from bridge.annotation_progress import Progress
import tempfile
from pathlib import Path


class NetworkTests(unittest.TestCase):
    def test_bounded_request_preserves_cache_and_sanitizes_url(self):
        manager=SimpleNamespace(_default_auth_func=lambda:None)
        response=SimpleNamespace(status_code=200,from_cache=True)
        events=[]
        auth=manager._default_auth_func
        with patch.dict('sys.modules',{'fastf1.internals.f1account':SimpleNamespace(token_manager=manager)}),patch.object(requests.sessions.Session,'send',return_value=response) as send:
            with bounded_network(lambda *a,**k:events.append((a,k))):
                result=requests.Session().get('https://livetiming.formula1.com/private/SessionInfo.json?token=SECRET')
                self.assertIs(result,response)
                self.assertEqual(send.call_args.kwargs['timeout'],(10,30))
                with self.assertRaises(FastF1AuthenticationRequired):manager._default_auth_func()
            self.assertIs(manager._default_auth_func,auth)
        self.assertNotIn('SECRET',str(events));self.assertTrue(events[1][1]['cacheHit'])

    def test_timeout_reported_and_hooks_restored(self):
        manager=SimpleNamespace(_default_auth_func=lambda:None)
        with tempfile.TemporaryDirectory() as temp:
            progress=Progress(Path(temp)/'report.json')
            with patch.dict('sys.modules',{'fastf1.internals.f1account':SimpleNamespace(token_manager=manager)}),patch.object(requests.sessions.Session,'send',side_effect=requests.ReadTimeout('SECRET')) as send:
                with self.assertRaises(requests.ReadTimeout):
                    with bounded_network(progress.event):requests.Session().get('https://example.test/SECRET',timeout=900)
                self.assertEqual(send.call_args.kwargs['timeout'],30)
            text=progress.path.read_text()
            self.assertIn('ReadTimeout',text);self.assertNotIn('SECRET',text)

    def test_endpoint_never_exports_unknown_paths(self):
        self.assertEqual(endpoint('https://example.test/private?token=SECRET'),'other-upstream')

    def test_probe_deadline_keeps_last_request(self):
        import json
        import subprocess
        from bridge.fastf1_probe import main
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'probe.json'
            path.write_text(json.dumps({'phase':'http-request','endpointKind':'SessionInfo','requestState':'started'}))
            with patch('sys.argv',['probe','--year','2026','--event','Mexico','--seconds','2','--report',str(path)]),patch('subprocess.run',side_effect=subprocess.TimeoutExpired('probe',2)) as run:
                self.assertEqual(main(),2)
            value=json.loads(path.read_text())
            self.assertEqual(value['state'],'timeout');self.assertEqual(value['endpointKind'],'SessionInfo')
            self.assertEqual(run.call_args.kwargs['stdin'],subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs['timeout'],2)

    def test_authentication_error_has_actionable_safe_code(self):
        from bridge.diagnostics import safe_exception
        error=safe_exception(FastF1AuthenticationRequired('SECRET'),'annotations')
        self.assertEqual(error['code'],'fastf1-authentication-required')
        self.assertNotIn('SECRET',str(error))
