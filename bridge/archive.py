"""Bounded LiveF1 static archive clips; no OpenF1 and no full-season download."""
import gzip
import hashlib
import json
import math
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from .protocol import TOPICS, RaceState, decode, utc_ms

BASE = 'https://livetiming.formula1.com/static/'
MAX_BYTES = 64 * 1024 * 1024
CACHE_BYTES = 128 * 1024 * 1024
MAX_SECONDS = 600


class ArchiveUnavailable(RuntimeError):
    pass


class TopicUnavailable(ArchiveUnavailable):
    pass


def elapsed_ms(value):
    hours, minutes, seconds = value.split(':')
    return (int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000


def safe_url(path):
    url = urljoin(BASE, path)
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'livetiming.formula1.com' or not parsed.path.startswith('/static/') or '..' in path:
        raise ValueError('Invalid LiveF1 archive path')
    return url


def response(path):
    from livef1.auth import auth_header
    result = requests.get(safe_url(path), headers=auth_header(), stream=True, timeout=(10, 30))
    if result.status_code in (401, 403):
        result.close()
        raise ArchiveUnavailable('Archive access requires local LiveF1 authentication/entitlement (HTTP 401/403). Run --login locally; never share credentials.')
    if not result.ok:
        code = result.status_code
        result.close()
        if code == 404:
            raise TopicUnavailable('Archive topic not published (HTTP 404).')
        raise ArchiveUnavailable(f'Archive request failed (HTTP {code}).')
    return result


def lines(path, budget, limit=MAX_BYTES):
    with response(path) as result:
        pending = b''
        for chunk in result.iter_content(65536):
            budget[0] += len(chunk)
            if budget[0] > limit:
                raise ArchiveUnavailable('Clip download exceeded 64 MiB; choose an earlier/shorter window or a local recording.')
            pending += chunk
            parts = pending.split(b'\n')
            pending = parts.pop()
            for line in parts:
                if len(line) > 2 * 1024 * 1024:
                    raise ArchiveUnavailable('Archive record exceeds size limit.')
                if line.strip():
                    yield line.decode('utf-8-sig').strip()
            if len(pending) > 2 * 1024 * 1024:
                raise ArchiveUnavailable('Archive record exceeds size limit.')
        if pending.strip():
            yield pending.decode('utf-8-sig').strip()


def small_json(path):
    budget = [0]
    text = '\n'.join(lines(path, budget, limit=2 * 1024 * 1024))
    if budget[0] > 2 * 1024 * 1024:
        raise ArchiveUnavailable('Archive index exceeds size limit.')
    return json.loads(text)


def list_sessions(year):
    if not 2018 <= int(year) <= 2100:
        raise ValueError('Year must be 2018–2100')
    index = small_json(f'{int(year)}/Index.json')
    return [{'path': session['Path'], 'label': f"{meeting.get('Name', '')} ({meeting.get('Location', '')}) · {session.get('Name', '')}",
             'start': session.get('StartDate')}
            for meeting in index.get('Meetings', []) for session in meeting.get('Sessions', []) if session.get('Path')]


def validate_clip(clip):
    if clip.get('format') != 'livef1-clip-v1' or clip.get('source') != 'LiveF1':
        raise ValueError('Only real LiveF1 clip recordings are accepted')
    if not 0 < clip.get('durationMs', 0) <= MAX_SECONDS * 1000:
        raise ValueError('Invalid clip duration')
    if not isinstance(clip.get('originMs'), (int, float)) or not math.isfinite(clip['originMs']):
        raise ValueError('Missing/invalid clip clock')
    if not isinstance(clip.get('initial'), dict) or not isinstance(clip.get('events'), list):
        raise ValueError('Invalid clip state/events')
    last = -1
    for event in clip['events']:
        offset = event.get('offsetMs')
        if not isinstance(offset, (int, float)) or offset < last or offset > clip['durationMs'] or event.get('topic') not in TOPICS:
            raise ValueError('Invalid clip event order/topic/time')
        last = offset
    return clip


def load_recording(path):
    path = Path(path)
    with path.open('rb') as handle:
        is_gzip = handle.read(2) == b'\x1f\x8b'
    opener = gzip.open if is_gzip else open
    with opener(path, 'rt', encoding='utf8') as handle:
        text = handle.read(MAX_BYTES + 1)
    if len(text.encode('utf8')) > MAX_BYTES:
        raise ValueError('Recording exceeds 64 MiB')
    return validate_clip(json.loads(text))


def save_clip(path, clip):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    encoded = json.dumps(clip, allow_nan=False, separators=(',', ':')).encode('utf8')
    if len(encoded) > MAX_BYTES:
        raise ValueError('Clip exceeds 64 MiB serialized limit')
    try:
        with gzip.open(temporary, 'wb') as handle:
            handle.write(encoded)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prune_cache(cache):
    files = sorted(Path(cache).glob('*.json.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for i, file in enumerate(files):
        total += file.stat().st_size
        if i >= 3 or total > CACHE_BYTES:
            file.unlink()


def fetch_clip(path, start_seconds=0, duration_seconds=120, cache='data-cache/livef1'):
    if not 0 <= start_seconds <= 4 * 3600 or not 1 <= duration_seconds <= MAX_SECONDS:
        raise ValueError('Start must be 0–14400 seconds, duration 1–600 seconds')
    safe_url(path)
    if not path.endswith('/'):
        raise ValueError('Select a session directory from the archive list')
    key = hashlib.sha256(f'{path}|{start_seconds}|{duration_seconds}|v1'.encode()).hexdigest()
    target = Path(cache) / f'{key}.json.gz'
    if target.exists():
        clip = load_recording(target)
        target.touch()
        return clip
    feeds = small_json(path + 'Index.json').get('Feeds', {})
    start = start_seconds * 1000
    end = start + duration_seconds * 1000
    budget = [0]
    events = []
    capabilities = {}
    origin = None
    # Read each topic lazily; stop once the requested window has been passed.
    # Pre-window timing is replayed into a seed so tyres/identity are not lost.
    seed = RaceState('TEST')
    for topic in TOPICS:
        feed = feeds.get(topic, {})
        stream = feed.get('StreamPath')
        if not stream:
            # Static identity/metadata are safe bootstrap fallbacks. Never use
            # final-session timing, tyre or flag keyframes as historical seeds.
            if topic in ('SessionInfo', 'DriverList') and feed.get('KeyFramePath'):
                try:
                    payload = small_json(urljoin(path, feed['KeyFramePath']))
                    if topic == 'DriverList':
                        fields = {'RacingNumber','Tla','BroadcastName','FullName','TeamName','TeamColour','FirstName','LastName'}
                        payload = {k:{f:v for f,v in driver.items() if f in fields}
                                   for k,driver in payload.items() if isinstance(driver,dict)}
                    seed.ingest(topic,payload,clock_ms=start)
                    capabilities[topic] = 'static-metadata-only'
                except TopicUnavailable:
                    capabilities[topic] = 'missing'
            else:
                capabilities[topic] = 'missing-stream'
            continue
        count = 0
        try:
            for line in lines(urljoin(path, stream), budget):
                offset = elapsed_ms(line[:12])
                if offset > end:
                    break
                payload = json.loads(line[12:])
                if topic == 'Position.z' and origin is None:
                    records = decode(topic, payload)
                    times = [utc_ms(r.get('Utc')) for r in records.values()]
                    times = [t for t in times if t is not None]
                    if times:
                        origin = max(times) - offset
                event = {'offsetMs': max(0, offset - start), 'topic': topic, 'payload': payload}
                if offset < start:
                    # Merge pre-roll immediately: no unbounded in-memory history.
                    seed.ingest(topic, payload, clock_ms=offset)
                else:
                    events.append(event)
                count += 1
            capabilities[topic] = 'available' if count else 'no-events-in-window'
        except TopicUnavailable:
            capabilities[topic] = 'missing'
        except ArchiveUnavailable:
            raise  # Authentication/network/size failure is not silent topic loss.
        except (ValueError, KeyError, TypeError):
            capabilities[topic] = 'parse-error'
    # Stable ordering across topic streams, including metadata at equal timestamps.
    order = {topic: i for i, topic in enumerate(TOPICS)}
    events.sort(key=lambda e: (e['offsetMs'], order[e['topic']]))
    if not events:
        raise ArchiveUnavailable('No real archive events in the selected window. Choose another session/window or a captured recording.')
    # No fabricated UTC: GPS establishes archive stream origin when available.
    # Relative clock 0 is explicitly reported if the GPS topic is missing.
    origin = origin if origin is not None else 0
    initial = seed.topics
    clip = {'format': 'livef1-clip-v1', 'source': 'LiveF1', 'sessionPath': path,
            'startOffsetSeconds': start_seconds, 'durationMs': duration_seconds * 1000, 'originMs': origin + start,
            'capabilities': capabilities, 'initial': initial, 'events': events,
            'initialFreshness': {topic: origin + offset for topic, offset in seed.freshness.items()},
            'capturedAt': time.time(), 'clockBasis': 'gps-utc' if origin else 'relative'}
    save_clip(target, validate_clip(clip))
    prune_cache(cache)
    return clip
