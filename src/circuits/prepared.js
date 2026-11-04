import {validateCalibration,calibrationGeometry} from './calibration.js';
import {geometryId,validateAnnotations} from './annotations.js';
import {defaultMotion,defaultFlagColors} from './defaults.js';

export function sessionCircuitKey(session) {
  const value=session?.Meeting?.Circuit?.Key;
  return value == null ? null : String(value);
}
export function sessionYear(session) {
  const value=String(session?.StartDate??'').slice(0,4);
  return /^20\d\d$/.test(value)?Number(value):null;
}
export function validatePrepared(bundle) {
  if(bundle?.schema!=='prepared-circuit-v1'||bundle.toolVersion!==1)throw Error('Invalid prepared asset schema');
  const meta=bundle.identity;
  const circuit={id:meta.id,layoutVersion:meta.layoutVersion};
  const calibration=validateCalibration(bundle.calibration,circuit.id,circuit.layoutVersion);
  const geometry=calibrationGeometry(calibration);
  if(geometryId(geometry)!==bundle.geometryId||!calibration.validation?.automaticChecksPassed||calibration.provenance?.synthetic)throw Error('Prepared geometry mismatch or failed quality checks');
  for(const field of ['corners','sectors'])if(bundle[field]){validateAnnotations(bundle[field],circuit,geometry);if(bundle[field].direction!==1)throw Error('Prepared annotation driving direction mismatch');}
  return bundle;
}
export function preparedForSession(bundles,session) {
  const key=sessionCircuitKey(session),year=sessionYear(session);
  if(!key||!year)return null;
  return Object.values(bundles).find(b=>b.identity.circuitKey===key&&b.identity.year===year)??null;
}
export function preparedCircuit(bundle) {
  const meta=bundle.identity;
  return {id:meta.id,name:meta.name,layoutVersion:meta.layoutVersion,motion:defaultMotion,flagColors:defaultFlagColors,sources:{livef1:{matrix:bundle.calibration.mapping.matrix}},annotations:{}};
}
// Measured source positions are compared with the outline, never snapped to it.
// This checks alignment, not proof of full-lap coverage or physical annotations.
export function gpsCompatibility(geometry,drivers,clockMs,minimum=5) {
  const errors=[];
  const diagonal=Math.hypot(geometry.width-1300,geometry.height-1300);
  for(const driver of drivers){
    if(driver.timing?.InPit===true||driver.timing?.PitIn===true)continue;
    const gps=driver.gps;
    if(!gps||![gps.X,gps.Y,gps._sampleTimeMs,clockMs].every(Number.isFinite)||clockMs-gps._sampleTimeMs>2500||clockMs-gps._sampleTimeMs< -2000||String(gps.Status??'OnTrack').toLowerCase()!=='ontrack')continue;
    const p=geometry.project(gps.X,gps.Y);
    let best=Infinity;
    for(let i=1;i<geometry.points.length;i++){
      const a=geometry.points[i-1],b=geometry.points[i],dx=b.x-a.x,dy=b.y-a.y;
      const t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy||1)));
      best=Math.min(best,Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy));
    }
    errors.push(best/diagonal);
  }
  errors.sort((a,b)=>a-b);
  const p95=errors.length?errors[Math.min(errors.length-1,Math.floor(errors.length*.95))]:null;
  return {status:errors.length<minimum?'waiting-for-gps':p95>.03?'incompatible':'compatible-sample',samples:errors.length,p95FractionOfDiagonal:p95};
}
