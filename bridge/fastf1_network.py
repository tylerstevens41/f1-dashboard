"""Bounded, credential-safe observation of the isolated FastF1 worker.

Delegates to FastF1's existing adapters/cache. No URLs, headers or response
bodies are exported. The pinned 3.9.0 token-manager hook prevents unattended
credential prompts; cached responses do not require authentication.
"""
from contextlib import contextmanager
from urllib.parse import urlsplit
import time


class FastF1AuthenticationRequired(RuntimeError):
    code = 'fastf1-authentication-required'


def endpoint(url):
    parsed=urlsplit(url)
    if parsed.hostname == 'livetiming.formula1.com':
        leaf=parsed.path.rsplit('/',1)[-1].split('.')[0]
        return leaf if leaf in {'SessionInfo','DriverList','SessionStatus','LapCount','TrackStatus','TimingData','TimingAppData','Position','CarData','Index'} else 'live-timing'
    if parsed.hostname in {'api.jolpi.ca','ergast.com'}:return 'race-results'
    if parsed.hostname == 'api.multiviewer.app':return 'circuit-metadata'
    return 'other-upstream'


@contextmanager
def bounded_network(report):
    import requests
    from fastf1.internals.f1account import token_manager
    original_send=requests.sessions.Session.send
    original_auth=token_manager._default_auth_func
    failures=[]

    def authenticate():
        report('fastf1-authentication-required')
        error=FastF1AuthenticationRequired('Authenticate FastF1 interactively in .venv-fastf1 before retrying.')
        failures.append(error)
        raise error

    def send(session,request,**kwargs):
        kind=endpoint(request.url)
        # Apply to every Session.send, including requests-cache and redirects.
        timeout=kwargs.get('timeout')
        if not isinstance(timeout,(int,float,tuple)):kwargs['timeout']=(10,30)
        elif isinstance(timeout,(int,float)):kwargs['timeout']=min(timeout,30)
        else:kwargs['timeout']=tuple(min(v or 30,30) for v in timeout)
        started=time.monotonic()
        report('http-request',endpointKind=kind,requestState='started')
        try:
            response=original_send(session,request,**kwargs)
        except Exception as exc:
            failures.append(exc)
            report('http-request',endpointKind=kind,requestState='failed',exceptionType=type(exc).__name__ if type(exc).__name__ in {'Timeout','ReadTimeout','ConnectTimeout','ConnectionError','FastF1AuthenticationRequired'} else 'RequestError',requestSeconds=round(time.monotonic()-started,3))
            raise
        report('http-request',endpointKind=kind,requestState='completed',httpStatus=response.status_code,cacheHit=bool(getattr(response,'from_cache',False)),requestSeconds=round(time.monotonic()-started,3))
        return response

    requests.sessions.Session.send=send
    token_manager._default_auth_func=authenticate
    try:yield failures
    finally:
        requests.sessions.Session.send=original_send
        token_manager._default_auth_func=original_auth
