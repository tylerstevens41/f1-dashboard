// Coordinates are source-local. Never apply a reference from another feed implicitly.
export const IDENTITY = [1, 0, 0, 1, 0, 0];

export function transformPoint(point, matrix = IDENTITY) {
  if (!point || (point.x ?? point.X) == null || (point.y ?? point.Y) == null) return null;
  const x = Number(point.x ?? point.X);
  const y = Number(point.y ?? point.Y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  const [a, b, c, d, e, f] = matrix;
  return { x: a * x + c * y + e, y: b * x + d * y + f };
}

export function createGeometry(reference, { padding = 650, matrix = IDENTITY } = {}) {
  const points = reference.map(p => transformPoint(p, matrix)).filter(Boolean);
  if (points.length < 2) return null;
  const minX = Math.min(...points.map(p => p.x));
  const maxX = Math.max(...points.map(p => p.x));
  const minY = Math.min(...points.map(p => p.y));
  const maxY = Math.max(...points.map(p => p.y));
  if (maxX <= minX || maxY <= minY) return null;
  const project = (x, y) => {
    const p = transformPoint({ x, y }, matrix);
    return p && { x: p.x - minX + padding, y: maxY - p.y + padding };
  };
  const projected = points.map(p => ({ x: p.x - minX + padding, y: maxY - p.y + padding }));
  const lengths = [0];
  for (let i = 1; i < projected.length; i++) lengths.push(lengths.at(-1) + Math.hypot(projected[i].x - projected[i-1].x, projected[i].y - projected[i-1].y));
  const total = lengths.at(-1);
  return {
    points: projected, project, lengths, total,
    path: projected.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' '),
    width: maxX - minX + padding * 2, height: maxY - minY + padding * 2,
  };
}

export function pointAt(geometry, fraction) {
  const distance = Math.max(0, Math.min(1, fraction)) * geometry.total;
  const i = Math.max(1, geometry.lengths.findIndex(v => v >= distance));
  const a = geometry.points[i-1], b = geometry.points[i];
  const span = geometry.lengths[i] - geometry.lengths[i-1];
  const t = span ? (distance - geometry.lengths[i-1]) / span : 0;
  return { x: a.x + (b.x-a.x)*t, y: a.y + (b.y-a.y)*t, angle: Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI };
}

// Explicit polyline subpaths share pointAt's cumulative-distance convention.
// This avoids relying on SVG dash phase to locate physical timing boundaries.
export function pathRange(geometry, start, end) {
  const a=pointAt(geometry,start),b=pointAt(geometry,end);
  const points=[a,...geometry.points.filter((_,i)=>geometry.lengths[i]>start*geometry.total && geometry.lengths[i]<end*geometry.total),b];
  return points.map((p,i)=>`${i?'L':'M'} ${p.x} ${p.y}`).join(' ');
}
