"""Credential-safe exception metadata. Never serialize exception messages/locals."""
from pathlib import Path
import re

BRIDGE = Path(__file__).resolve().parent
HINTS = {
    'archive': 'Inspect archiveTopicErrors and formatKind: parsing failure is distinct from missing GPS or lap rejection. HTML/markup may be a login, security or routing response; do not share raw response bodies.',
    'extract': 'Check Position.z decoder/schema and session-clock diagnostics; timing messages are required for lap grouping.',
    'clean': 'Inspect sample/lap rejection counts and timestamps before changing quality thresholds.',
    'build': 'Inspect calibration checks and repository exception location; do not force a closed outline.',
    'cache': 'Inspect the disposable GPS sample cache and disk permissions; existing circuit assets are unchanged.',
    'identity': 'Compare published circuit metadata with the requested circuit key; do not substitute another layout.',
}


def safe_exception(exc, stage):
    name = type(exc).__name__
    name = name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'Exception'
    result = {'exceptionType': name, 'stage': stage, 'messageSuppressed': True,
              'hint': HINTS.get(stage, 'Inspect local dependency installation and job diagnostics; no raw upstream error was exported.')}
    code = getattr(exc, 'code', None)
    if code in {'authentication-required','topic-unpublished','archive-http-error','download-limit','no-events','record-limit','invalid-clip-schema','invalid-event-schema','invalid-position-record-schema','invalid-stream-format'}:
        result['code'] = code
    if getattr(exc,'formatKind',None) in {'html-or-markup','json-without-elapsed-prefix','quoted-without-elapsed-prefix','unsupported-prefix'}:
        result['formatKind']=exc.formatKind
        result['prefixShape']=exc.prefixShape
    if isinstance(exc, ModuleNotFoundError) and isinstance(exc.name, str) and re.fullmatch(r'[A-Za-z0-9_.]{1,80}', exc.name):
        result['missingModule'] = exc.name
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    if isinstance(status, int) and 100 <= status <= 599:
        result['httpStatus'] = status
    # Only locations inside this repository's bridge are exposed; no filesystem
    # user names, source text, raw values, traceback locals, URLs or auth headers.
    locations = []
    trace = exc.__traceback__
    while trace:
        file = Path(trace.tb_frame.f_code.co_filename).resolve()
        if file.parent == BRIDGE:
            locations.append({'file': file.name, 'function': trace.tb_frame.f_code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    if locations:
        result['location'] = locations[-1]
    return result
