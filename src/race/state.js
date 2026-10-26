export function initialRaceState() {
  return { topics: {}, freshness: {}, capabilities: {}, generation: null, sequence: -1,
    mode: 'LIVE', clockBasis: 'utc', sessionId: null, upstream: 'idle', playback: 'stopped', speed: 1, clockMs: null };
}

export function raceReducer(state, message) {
  if (!message || message.version !== 1 || !['snapshot', 'topic', 'status'].includes(message.type)) return state;
  if (message.type !== 'snapshot' && state.generation !== null &&
    (message.generation < state.generation || (message.generation === state.generation && message.sequence <= state.sequence))) return state;
  let next = message.type === 'snapshot' || message.generation !== state.generation ? initialRaceState() : state;
  next = { ...next, generation: message.generation, sequence: message.sequence, mode: message.mode,
    sessionId: message.sessionId, upstream: message.upstream, playback: message.playback,
    speed: message.speed, clockMs: message.clockMs, clockBasis: message.clockBasis, error: message.error ?? null };
  if (message.type === 'snapshot') return { ...next, topics: message.topics ?? {}, freshness: message.freshness ?? {}, capabilities: message.capabilities ?? {} };
  if (message.type === 'topic' && typeof message.topic === 'string' && message.data && typeof message.data === 'object') {
    return { ...next, topics: { ...next.topics, [message.topic]: message.data },
      freshness: { ...next.freshness, [message.topic]: message.updatedAt } };
  }
  return next;
}

// Presentation adapter only. Authoritative state retains nested dictionaries so
// sparse tyre/sector deltas cannot replace unrelated driver fields.
export function flattenRecord(value, prefix = '', output = {}) {
  for (const [key, item] of Object.entries(value ?? {})) {
    const path = prefix ? `${prefix}_${key}` : key;
    if (item && typeof item === 'object') flattenRecord(item, path, output);
    else output[path] = item;
  }
  return output;
}

export function selectCircuit(session) {
  const name = session?.Meeting?.Circuit?.ShortName ?? session?.Meeting_Circuit_ShortName ?? '';
  return /^(austin|circuit of the americas|cota)$/i.test(name) ? 'Austin' : null;
}

export function validGps(gps, clockMs, maxAgeMs = 20000) {
  return gps && Number.isFinite(gps.X) && Number.isFinite(gps.Y) &&
    Number.isFinite(gps._sampleTimeMs) && Number.isFinite(clockMs) &&
    clockMs - gps._sampleTimeMs >= -2000 && clockMs - gps._sampleTimeMs <= maxAgeMs;
}

export function freshnessAge(state, topic, clockMs) {
  const time = state.freshness[topic];
  return Number.isFinite(time) && Number.isFinite(clockMs) ? Math.max(0, clockMs - time) : null;
}

export function tyrePresentation(record) {
  const flattened = flattenRecord(record);
  const stints = Object.entries(record?.Stints ?? {}).filter(([key, value]) => /^\d+$/.test(key) && value && typeof value === 'object');
  stints.sort((a,b) => Number(a[0]) - Number(b[0]));
  const current = stints.at(-1)?.[1];
  if (current) {
    flattened.CurrentStint_Compound = current.Compound;
    flattened.CurrentStint_TotalLaps = current.TotalLaps;
  }
  return flattened;
}
