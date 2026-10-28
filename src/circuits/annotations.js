// Fractions refer to distance along the exact geometry path, not screen pixels.
export const palette=['#ed3897','#f6ce42','#40bff2'];
export const defaultAppearance={base:'charcoal',trackWidth:330,lineWidth:65,cornerLabelScale:1.65,cornerLabelSpacing:1.15,corners:true,boundaries:true,drs:true,speedTraps:true,startFinish:true,pitLane:true};
export const bases={black:'#090b0e',charcoal:'#303743',grey:'#727982'};
export const emptyAnnotations=(circuit,geometry)=>({schema:'f1-circuit-annotations-v1',circuitId:circuit.id,layoutVersion:circuit.layoutVersion,geometryId:geometryId(geometry),direction:1,startFinish:null,sector1End:null,sector2End:null,corners:[],detectionPoints:[],zones:[],speedTraps:[],pitLane:null,provenance:''});
export function geometryId(geometry){
  let hash=2166136261;
  for(const ch of geometry.points.map(p=>`${p.x.toFixed(3)},${p.y.toFixed(3)}`).join(';')) hash=Math.imul(hash^ch.charCodeAt(0),16777619);
  return (hash>>>0).toString(16);
}
const validFraction=x=>typeof x==='number' && Number.isFinite(x) && x>=0 && x<1;
export function validateAnnotations(data,circuit,geometry){
  if(!data || data.schema!=='f1-circuit-annotations-v1' || data.circuitId!==circuit.id || data.layoutVersion!==circuit.layoutVersion || data.geometryId!==geometryId(geometry))throw Error('Annotation circuit, layout, or geometry mismatch');
  if(![1,-1].includes(data.direction))throw Error('Direction must be 1 or -1');
  for(const key of ['startFinish','sector1End','sector2End']) if(data[key]!==null && (!validFraction(data[key]?.at)||!['provisional','verified'].includes(data[key]?.status)))throw Error(`Invalid ${key}`);
  if(!Array.isArray(data.corners)||data.corners.some(c=>!Number.isInteger(c.number)||c.number<1||! /^[A-Za-z]*$/.test(c.letter??'')||!validFraction(c.at)||!['provisional','verified'].includes(c.status)) || new Set(data.corners.map(c=>`${c.number}${c.letter??''}`)).size!==data.corners.length)throw Error('Invalid corners');
  for(const k of ['detectionPoints','zones','speedTraps'])if(!Array.isArray(data[k]))throw Error(`Invalid ${k}`);
  for(const k of ['detectionPoints','speedTraps'])if(data[k].some(x=>!validFraction(x.at)||!['provisional','verified'].includes(x.status)))throw Error(`Invalid ${k}`);
  if(data.zones.some(x=>!validFraction(x.start)||!validFraction(x.end)||x.start===x.end||!['provisional','verified'].includes(x.status)))throw Error('Invalid zones');
  if(data.pitLane!==null && (typeof data.pitLane?.path!=='string'||!['provisional','verified'].includes(data.pitLane.status)))throw Error('Invalid pit lane');
  const first=geometry.points[0],last=geometry.points.at(-1);
  if(data.startFinish && Math.hypot(first.x-last.x,first.y-last.y)>0.01)throw Error('A closed calibrated path is required for lap annotations');
  if(data.startFinish&&data.sector1End&&data.sector2End&&!sectorRanges(data))throw Error('Sector order does not follow the selected direction');
  if([data.startFinish,data.sector1End,data.sector2End,...data.corners,...data.detectionPoints,...data.zones,...data.speedTraps,data.pitLane].some(x=>x?.status==='verified')&&!data.provenance?.trim())throw Error('Verified annotations require provenance');
  return data;
}
const mod=x=>(x%1+1)%1;
export function sectorRanges(data){
  if(!data?.startFinish||!data.sector1End||!data.sector2End)return null;
  const s=data.startFinish.at, a=data.sector1End.at,b=data.sector2End.at,dir=data.direction;
  if(![s,a,b].every(validFraction)||![1,-1].includes(dir))return null;
  const d1=mod((a-s)*dir),d2=mod((b-s)*dir);
  if(d1<1e-8 || d2<=d1+1e-8 || d2>=1-1e-8)return null;
  // SVG follows increasing geometry distance, irrespective of driving direction.
  const split=(from,to)=>{const x=dir===1?from:to,y=dir===1?to:from;return x<y?[[x,y]]:[[x,1],[0,y]];};
  return [split(s,a),split(a,b),split(b,s)];
}
export function nearestFraction(geometry,x,y){
  let best=Infinity,distance=0;
  for(let i=1;i<geometry.points.length;i++){
    const a=geometry.points[i-1],b=geometry.points[i],dx=b.x-a.x,dy=b.y-a.y,den=dx*dx+dy*dy;
    const t=den?Math.max(0,Math.min(1,((x-a.x)*dx+(y-a.y)*dy)/den)):0;
    const dist=(x-a.x-t*dx)**2+(y-a.y-t*dy)**2;
    if(dist<best){best=dist;distance=geometry.lengths[i-1]+t*Math.sqrt(den);}
  }
  return Math.min(0.999999999,distance/geometry.total);
}

export const cornerKey=c=>`${c.number}${c.letter??''}`;
export function mergeImportedCorners(base, edits){
  const corners=new Map((base.corners??[]).map(c=>[cornerKey(c),c]));
  for(const c of edits?.corners??[])corners.set(cornerKey(c),{...corners.get(cornerKey(c)),...c});
  const merged={...base,...edits,corners:[...corners.values()],importSource:(base.corners?.length?base.importSource:null)??(edits?.corners?.length?edits.importSource:null)??base.importSource??edits?.importSource,alignment:base.alignment??edits?.alignment};
  for(const key of ['startFinish','sector1End','sector2End']){
    const original=base[key],override=edits?.[key];
    if(original?.calculated){
      const manual=override && (override.manualOverride || override.status==='verified' || !override.calculated);
      merged[key]=edits?.boundaryOverrides?.[key] ? override??null : manual ? {...original,...override,sourceEstimate:original.sourceEstimate} : override?.preferCalculated ? {...original,at:original.sourceEstimate.at,status:'provisional',manualOverride:false,preferCalculated:true,previousOverride:override.previousOverride} : original;
    }
  }
  const manualBoundaries=['startFinish','sector1End','sector2End'].some(k=>edits?.[k] && (edits[k].manualOverride||edits[k].status==='verified'||!edits[k].calculated));
  if(base.boundaryDiagnostics && !manualBoundaries && !edits?.manualDirection)merged.direction=base.direction;
  merged.boundaryDiagnostics=base.boundaryDiagnostics??edits?.boundaryDiagnostics;
  merged.sectorSource=base.sectorSource??edits?.sectorSource;
  merged.sectorImportSource=base.sectorImportSource??edits?.sectorImportSource??(base.boundaryDiagnostics?base.importSource:undefined);
  return merged;
}
export function placeAnnotation(value,placing,at){
  if(!Number.isFinite(at)||at<0||at>=1)throw Error('Placement could not be mapped to the track');
  if(placing.kind==='corner'){
    const key=cornerKey(placing),existing=value.corners.find(c=>cornerKey(c)===key);
    const feature={...existing,number:placing.number,letter:placing.letter??'',at,status:'provisional',hidden:false,manualOverride:true};
    return {...value,corners:[...value.corners.filter(c=>cornerKey(c)!==key),feature]};
  }
  return {...value,boundaryOverrides:{...value.boundaryOverrides,[placing.kind]:false},[placing.kind]:{...value[placing.kind],at,status:'provisional',manualOverride:true}};
}
