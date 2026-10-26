"""Raw LiveF1 topics -> stable, bounded dashboard state (protocol version 1)."""
import copy
import math
from datetime import datetime, timezone

TOPICS = ('SessionInfo', 'DriverList', 'TimingData', 'TimingAppData', 'Position.z',
          'CarData.z', 'TrackStatus', 'RaceControlMessages', 'SessionStatus', 'SessionData')


def merge(previous, patch):
    """Merge sparse dictionaries/array-index deltas; null clears, _deleted removes."""
    if isinstance(patch, list):
        patch = {str(i): v for i, v in enumerate(patch)}
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    if isinstance(previous, list):
        previous = {str(i): v for i, v in enumerate(previous)}
    result = copy.deepcopy(previous) if isinstance(previous, dict) else {}
    for key in patch.get('_deleted', []) if isinstance(patch.get('_deleted'), list) else []:
        result.pop(str(key), None)
    for key, value in patch.items():
        if key == '_deleted':
            continue
        key = str(key)
        if isinstance(value, dict) and value.get('_deleted') is True:
            result.pop(key, None)
        else:
            result[key] = merge(result.get(key), value)
    return result


def utc_ms(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except (ValueError, TypeError):
        return None


def decode(topic, payload, timestamp=None):
    """Use installed LiveF1 decoders only for compressed streams.

    Other topics stay nested: LiveF1 1.3.0 lacks TimingAppData parsing and its
    flatteners can discard identity/index semantics in sparse updates.
    """
    if topic in ('Position.z', 'CarData.z'):
        from livef1.data_processing.etl import function_map
        records = list(function_map[topic]([(timestamp, payload)], None))
        drivers = {}
        for record in records:
            number = str(record['DriverNo'])
            previous = drivers.get(number)
            batch = (previous or {}).get('_batch', []) + [record]
            newest = max(batch, key=lambda r: utc_ms(r.get('Utc')) or -math.inf)
            drivers[number] = {**newest, '_batch': batch} if topic == 'Position.z' else newest
        return drivers
    if not isinstance(payload, dict):
        raise ValueError('Expected raw topic object')
    if topic in ('TimingData', 'TimingAppData'):
        return payload.get('Lines', {})
    if topic == 'DriverList':
        return {str(k): {**v, 'RacingNumber': str(v.get('RacingNumber', k))}
                for k, v in payload.items() if isinstance(v, dict)}
    return payload


class RaceState:
    def __init__(self, mode='LIVE'):
        self.reset(mode)

    def reset(self, mode, session_id=None):
        self.mode = mode
        self.clock_basis = 'utc' if mode == 'LIVE' else 'relative'
        self.session_id = session_id
        self.generation = getattr(self, 'generation', 0) + 1
        self.sequence = 0
        self.topics = {}
        self.freshness = {}
        self.clock_ms = None
        self.upstream = 'idle'
        self.playback = 'stopped'
        self.speed = 1
        self.capabilities = {}

    def envelope(self, kind, **extra):
        self.sequence += 1
        return {'version': 1, 'type': kind, 'generation': self.generation,
                'sequence': self.sequence, 'mode': self.mode, 'sessionId': self.session_id,
                'clockMs': self.clock_ms, 'clockBasis': self.clock_basis, 'upstream': self.upstream,
                'playback': self.playback, 'speed': self.speed, **extra}

    def snapshot(self):
        return self.envelope('snapshot', topics=copy.deepcopy(self.topics),
                             freshness=dict(self.freshness), capabilities=self.capabilities)

    def ingest(self, topic, payload, timestamp=None, clock_ms=None):
        if topic not in TOPICS:
            return []
        data = decode(topic, payload, timestamp)
        messages = []
        if topic == 'SessionInfo':
            old_info = self.topics.get('SessionInfo', {})
            incoming_id = data.get('Key')
            if incoming_id is None:
                path = data.get('Path')
                if self.session_id is None or (path and old_info.get('Path') and path != old_info['Path']):
                    incoming_id = path
            if incoming_id is not None:
                incoming_id = str(incoming_id)
                if self.session_id is not None and self.session_id != incoming_id:
                    upstream, playback, speed = self.upstream, self.playback, self.speed
                    capabilities, clock_basis = self.capabilities, self.clock_basis
                    self.reset(self.mode, incoming_id)
                    self.upstream, self.playback, self.speed = upstream, playback, speed
                    self.capabilities, self.clock_basis = capabilities, clock_basis
                    messages.append(self.snapshot())
                self.session_id = incoming_id
        self.clock_ms = clock_ms if clock_ms is not None else utc_ms(timestamp)
        if self.clock_ms is None:
            self.clock_ms = datetime.now(timezone.utc).timestamp() * 1000
        previous = self.topics.get(topic, {})
        if topic in ('Position.z', 'CarData.z'):
            # Keep newest per driver; a missing sample must not erase another car.
            accepted = {}
            for number, record in data.items():
                sample_time = utc_ms(record.get('Utc')) or self.clock_ms
                old = previous.get(number, {})
                if sample_time < old.get('_sampleTimeMs', -math.inf):
                    continue
                if topic == 'Position.z' and not all(
                    isinstance(record.get(k), (int, float)) and not isinstance(record[k], bool)
                    and math.isfinite(record[k]) for k in ('X', 'Y')
                ):
                    continue
                history = list(old.get('_history', []))
                for sample in sorted(record.get('_batch', [record]), key=lambda r: utc_ms(r.get('Utc')) or 0):
                    t = utc_ms(sample.get('Utc'))
                    if t is None or (history and t <= history[-1]['time']):
                        continue
                    if all(isinstance(sample.get(k),(int,float)) and not isinstance(sample[k],bool) and math.isfinite(sample[k]) for k in ('X','Y')):
                        history.append({'time':t,'x':sample['X'],'y':sample['Y']})
                accepted[number] = {k:v for k,v in record.items() if k != '_batch'}
                accepted[number]['_sampleTimeMs'] = sample_time
                if topic == 'Position.z':
                    accepted[number]['_history'] = history[-24:]
            data = accepted
            if not data:
                return messages
        self.topics[topic] = merge(previous, data)
        if topic == 'Position.z':
            for number,record in data.items():
                self.topics[topic][number]['_history'] = record['_history']
        if topic == 'RaceControlMessages':
            all_messages = self.topics[topic].get('Messages', {})
            if isinstance(all_messages, dict):
                self.topics[topic]['Messages'] = dict(list(all_messages.items())[-100:])
        self.freshness[topic] = self.clock_ms
        # Send authoritative per-topic state: reconnect and sparse deltas have the
        # same frontend semantics. Compressed topics remain bounded to one/car.
        messages.append(self.envelope('topic', topic=topic, data=self.topics[topic],
                                      updatedAt=self.clock_ms))
        return messages
