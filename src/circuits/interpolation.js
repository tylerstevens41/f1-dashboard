// No extrapolation and no centreline snapping. Distances use native feed units.
export function interpolateSamples(samples, time, { maxGapMs=1500, staleMs=2500, maxUnitsPerMs=2 } = {}) {
  if (!samples?.length || !Number.isFinite(time)) return null;
  const valid=samples.filter(p => Number.isFinite(p.time) && Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!valid.length) return null;
  let low=0,high=valid.length;
  while(low<high){ const mid=(low+high)>>1; if(valid[mid].time<=time)low=mid+1;else high=mid; }
  const previous=valid[low-1], next=valid[low];
  if (!previous || time-previous.time>staleMs) return null;
  if (!next || next.time-previous.time>maxGapMs) return {x:previous.x,y:previous.y,held:true};
  const gap=next.time-previous.time;
  if (gap<=0) return {x:previous.x,y:previous.y,held:true};
  if (Math.hypot(next.x-previous.x,next.y-previous.y)/gap>maxUnitsPerMs) return null;
  const t=(time-previous.time)/gap;
  return {x:previous.x+(next.x-previous.x)*t,y:previous.y+(next.y-previous.y)*t,held:false};
}

export function appendSample(history, point, { maxGapMs=1500, maxUnitsPerMs=2 } = {}) {
  if (![point?.x,point?.y,point?.time].every(Number.isFinite))return history;
  const last=history.at(-1);
  if(last && point.time<=last.time)return history;
  // A gap starts a new continuous segment: do not interpolate across the outage.
  if(last && point.time-last.time>maxGapMs)return [point];
  if(last && Math.hypot(point.x-last.x,point.y-last.y)/(point.time-last.time)>maxUnitsPerMs)return history;
  return [...history,point].slice(-24);
}
