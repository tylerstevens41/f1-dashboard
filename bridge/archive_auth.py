"""Pinned LiveF1 1.3 auth seam for bounded non-interactive metadata requests.

Reuse the SDK's token/configuration and public login API; never log credentials,
copy a WebSocket cookie, mutate SDK globals, or prompt from a background task.
"""
import os
import threading
import time

_LOCK=threading.Lock()
_LAST_REFRESH=0.0


def headers(force=False,rejected=None):
    from livef1 import auth
    global _LAST_REFRESH
    with _LOCK:
        current=auth.auth_header()
        if current and (not force or rejected is not None and current!=rejected):return current,False
        # Credential-path resolution is a version-pinned read-only seam. Using
        # the SDK helpers preserves livef1.configure/env-file precedence exactly.
        # Explicit credentials make login incapable of prompting on this path.
        try:
            values=auth._read_env(auth._env_path(None))
            username=os.environ.get(auth.ENV_USERNAME) or values.get(auth.ENV_USERNAME)
            password=os.environ.get(auth.ENV_PASSWORD) or values.get(auth.ENV_PASSWORD)
        except Exception:return current,False
        if not username or not password:return current,False
        now=time.monotonic()
        if _LAST_REFRESH and now-_LAST_REFRESH<60:return current,False
        _LAST_REFRESH=now
        try:
            token=auth.login(username=username,password=password,force=force)
            return token.header,True
        except Exception:
            # No upstream exception text, credential values or filenames escape.
            return auth.auth_header(),True
        finally:
            _LAST_REFRESH=time.monotonic()
