import { createGeometry, transformPoint, IDENTITY } from './geometry.js';

export function validateCalibration(data, circuitId, layoutVersion) {
  if (!data || data.schema !== 'livef1-circuit-calibration-v1' || data.circuitId !== circuitId || data.source !== 'LiveF1') throw new Error('Calibration schema/circuit/source mismatch');
  if (!['candidate','verified'].includes(data.status) || !data.layoutVersion) throw new Error('Invalid calibration status/layout');
  if (layoutVersion && data.layoutVersion !== layoutVersion) throw new Error('Calibration layout version mismatch');
  const points=data.geometry?.points;
  const matrix=data.mapping?.matrix;
  if (!Array.isArray(points) || points.length < 45 || points.length > 4096 || !points.every(p => typeof p.x === 'number' && typeof p.y === 'number' && Number.isFinite(p.x) && Number.isFinite(p.y))) throw new Error('Invalid calibration geometry');
  if (!Array.isArray(matrix) || matrix.length !== 6 || !matrix.every(Number.isFinite) || Math.abs(matrix[0]*matrix[3]-matrix[1]*matrix[2])<1e-12) throw new Error('Invalid calibration matrix');
  if (data.status==='verified' && (!data.validation?.verified || data.provenance?.synthetic)) throw new Error('Calibration verification metadata invalid');
  if (!createGeometry(points)) throw new Error('Degenerate calibration geometry');
  return data;
}

// Calibration geometry is already in target/native coordinates. Only incoming
// cars pass through the mapping, never the calibrated outline a second time.
export function calibrationGeometry(data, legacyPoints) {
  const geometry=createGeometry(data?.geometry.points ?? legacyPoints);
  if (!geometry) return null;
  const baseProject=geometry.project;
  return { ...geometry, project: (x,y) => {
    const point=transformPoint({x,y},data?.mapping.matrix ?? IDENTITY);
    return point && baseProject(point.x,point.y);
  }, projectNative: baseProject };
}
