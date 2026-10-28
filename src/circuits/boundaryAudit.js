import {pointAt} from './geometry.js';
export const boundaryKeys=['startFinish','sector1End','sector2End'];
const circularDelta=(a,b)=>(a-b+1.5)%1-.5;
export function boundaryDisplayAudit(annotations,geometry,files={}){
  return boundaryKeys.map(key=>{
    const feature=annotations[key],computed=feature?.sourceEstimate?.at??files.sectorFile?.[key]?.at;
    let origin=feature?.calculated?(files.calculatedOrigin??'calculated-file'):'unconfigured';
    if(annotations.boundaryEffectiveSources?.[key])origin=annotations.boundaryEffectiveSources[key];
    else for(const [name,file] of [['corner-file',files.cornerFile],['manual-file',files.annotationFile],['browser-draft',files.saved],['in-memory-edit',files.draft]]){
      const entry=file?.[key];
      if(entry && feature && entry.at===feature.at && (entry.manualOverride||entry.status==='verified'||!entry.calculated))origin=name;
    }
    if(!annotations.boundaryEffectiveSources && feature?.preferCalculated && !feature.manualOverride)origin='explicit-calculated-choice';
    const different=Number.isFinite(computed) && feature && Math.abs(circularDelta(feature.at,computed))>1e-6;
    return {key,calculatedAt:computed??null,displayedAt:feature?.at??null,origin,different:Boolean(different),
      deltaNative:different?circularDelta(feature.at,computed)*geometry.total:0,
      displayedPoint:feature?pointAt(geometry,feature.at):null,calculatedPoint:Number.isFinite(computed)?pointAt(geometry,computed):null};
  });
}
export function calculatedBoundaryPreview(annotations){
  if(annotations.boundaryCalculatedPositions){
    const entries=boundaryKeys.filter(k=>annotations.boundaryCalculatedPositions[k]).map(k=>[k,{...annotations.boundaryCalculatedPositions[k],manualOverride:false,explicitManualSelection:false}]);
    if(!entries.length)return annotations;
    return {...annotations,...Object.fromEntries(entries),direction:annotations.boundaryCalculatedDirection??annotations.direction,boundaryEffectiveSources:{...annotations.boundaryEffectiveSources,...Object.fromEntries(entries.map(([k])=>[k,'calculated-preview']))}};
  }
  if(!boundaryKeys.every(k=>Number.isFinite(annotations[k]?.sourceEstimate?.at)))return annotations;
  return {...annotations,direction:annotations.boundaryDiagnostics?.registration?.direction??annotations.direction,
    ...Object.fromEntries(boundaryKeys.map(k=>[k,{...annotations[k],at:annotations[k].sourceEstimate.at,calculated:true,manualOverride:false,status:'provisional'}]))};
}
export function browserBoundaryAudit(annotations,geometry,rows,svg){
  const segments=[...(svg?.querySelectorAll('[data-sector]')??[])].map(path=>{
    const start=path.getPointAtLength(0),end=path.getPointAtLength(path.getTotalLength());
    return {sector:Number(path.dataset.sector),startAt:Number(path.dataset.start),endAt:Number(path.dataset.end),start:{x:start.x,y:start.y},end:{x:end.x,y:end.y}};
  });
  return {schema:'f1-boundary-browser-audit-v1',circuitId:annotations.circuitId,layoutVersion:annotations.layoutVersion,geometryId:annotations.geometryId,
    direction:annotations.direction,pathLengthNative:geometry.total,boundaries:rows,renderedSegments:segments,
    cornerAnchors:annotations.corners.map(c=>({number:c.number,letter:c.letter??'',at:c.at,point:pointAt(geometry,c.at),offset:c.offset??null}))};
}
export function downloadAudit(value){
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='f1-boundary-browser-audit.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
