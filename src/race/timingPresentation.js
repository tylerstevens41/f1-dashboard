// Presentation only: never derive a car-ahead interval from leader gaps.
export function intervalToAhead(timing, position) {
  if (Number(position) === 1) return '—';
  const value = timing?.IntervalToPositionAhead?.Value
    ?? timing?.IntervalToPositionAhead_Value
    ?? timing?.IntervalToPositionAhead;
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '—';
  return typeof value === 'string' && value.trim() ? value.trim() : '—';
}
