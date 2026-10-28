import austinReference from '../../config/circuit-references/austin-2026.json';
import { useState } from 'react';
import { emptyAnnotations, validateAnnotations, cornerKey } from './annotations';

export default function AnnotationEditor({circuit,geometry,value,onChange,placing,setPlacing,onSelect}){
  const [kind,setKind]=useState('startFinish');
  const [turn,setTurn]=useState(1);
  const [letter,setLetter]=useState('');
  const [error,setError]=useState('');
  const selected=kind==='corner'?value.corners.find(c=>cornerKey(c)===cornerKey({number:turn,letter})):value[kind];
  const update=patch=>{
    if(!selected)return;
    if(kind==='corner')onChange({...value,corners:value.corners.map(c=>cornerKey(c)===cornerKey({number:turn,letter})?{...c,status:'provisional',...patch,manualOverride:true}:c)});
    else onChange({...value,boundaryOverrides:{...value.boundaryOverrides,[kind]:false},[kind]:{...selected,status:'provisional',...patch,manualOverride:true}});
  };
  const exportJson=()=>{try{validateAnnotations(value,circuit,geometry);const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${circuit.id}-annotations.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setError('');}catch(e){setError(e.message);}};
  return <details className="circuit-dev-panel" onToggle={e=>{if(!e.currentTarget.open)setPlacing(null);}}><summary>Annotation editor (development)</summary>
    <p>Positions are path fractions on this exact calibration. All clicks are provisional. Confirm direction, finish and sector positions against an event map before marking verified.</p>
    <label>Type <select value={kind} onChange={e=>{setKind(e.target.value);onSelect({kind:e.target.value,number:turn,letter});setPlacing(null);}}><option value="startFinish">Start / finish</option><option value="sector1End">Sector 1 end</option><option value="sector2End">Sector 2 end</option><option value="corner">Corner</option></select></label>{' '}
    {kind==='corner' && <><label>Turn <input type="number" min="1" max="99" value={turn} onChange={e=>{setTurn(Number(e.target.value));onSelect({kind,number:Number(e.target.value),letter});}}/></label><label>Letter <input size="2" value={letter} onChange={e=>{const l=e.target.value.replace(/[^a-z]/gi,'').toUpperCase();setLetter(l);onSelect({kind,number:turn,letter:l});}}/></label></>}{' '}
    <button onClick={()=>{const next={kind,number:turn,letter};onSelect(next);setPlacing(placing?null:next);}}>{placing?'Cancel placement':'Click track to place / move'}</button>{' '}
    <label>Driving direction <select value={value.direction} onChange={e=>{const provisional=x=>x?{...x,status:'provisional'}:null;onChange({...value,manualDirection:true,direction:Number(e.target.value),startFinish:provisional(value.startFinish),sector1End:provisional(value.sector1End),sector2End:provisional(value.sector2End)});}}><option value="1">Along geometry</option><option value="-1">Opposite geometry</option></select></label>
    <p>Selected: {selected ? `${selected.at.toFixed(5)} · ${(selected.at*geometry.total).toFixed(1)} native path units · ${selected.status}` : 'not placed'}{selected?.sourceEstimate && ` · calculated ${selected.sourceEstimate.at.toFixed(5)} · p95 spread ${(selected.sourceEstimate.statistics.p95LapFraction*100).toFixed(3)}% lap`} · geometry {value.geometryId}{selected?.imported && ` · FastF1 anchor error ${selected.alignmentError?.toFixed(1)??'—'} native units · ${selected.manualOverride?'manual override':'imported default'}`}</p>
    {selected?.sourceEstimate && kind!=='corner' && <button onClick={()=>onChange({...value,boundaryOverrides:{...value.boundaryOverrides,[kind]:false},[kind]:{...selected,at:selected.sourceEstimate.at,status:'provisional',calculated:true,manualOverride:false,preferCalculated:true,previousOverride:{at:selected.at,status:selected.status}}})}>Use calculated position (replace this override)</button>}
    {selected && <><label>Offset X <input type="number" value={selected.offset?.x??0} onChange={e=>update({offset:{...selected.offset,x:Number(e.target.value)}})}/></label><label> Offset Y <input type="number" value={selected.offset?.y??-245} onChange={e=>update({offset:{...selected.offset,y:Number(e.target.value)}})}/></label>{' '}
    {kind==='corner' && <button onClick={()=>update({hidden:!selected.hidden})}>{selected.hidden?'Show label':'Hide label'}</button>}<button onClick={()=>kind==='corner'?update({hidden:true}):onChange({...value,boundaryOverrides:{...value.boundaryOverrides,[kind]:true},[kind]:null})}>Delete</button></>}
    <p>Provenance: <input value={value.provenance} onChange={e=>onChange({...value,provenance:e.target.value})} placeholder="Evidence / local verification"/> <button disabled={!selected||!value.provenance.trim()} onClick={()=>update({status:selected.status==='verified'?'provisional':'verified'})}>Toggle verified</button></p>
    {circuit.id==='austin' && <p>2026 FIA map: S1 1.658 km, S2 1.941 km, S3 1.914 km; S1 is 65 m before T7, S2 65 m before T13. <button disabled={!value.startFinish} onClick={()=>{const s=value.startFinish.at,d=value.direction,wrap=x=>(x%1+1)%1;onChange({...value,sector1End:{at:wrap(s+d*austinReference.sectorLengthsMetres[0]/austinReference.lengthMetres),status:'provisional'},sector2End:{at:wrap(s+d*(austinReference.sectorLengthsMetres[0]+austinReference.sectorLengthsMetres[1])/austinReference.lengthMetres),status:'provisional'}});}}>Estimate from FIA distances</button></p>}
    <button onClick={exportJson}>Export JSON</button>{' '}<button onClick={()=>onChange({...emptyAnnotations(circuit,geometry),boundaryOverrides:{startFinish:true,sector1End:true,sector2End:true},corners:value.corners.filter(c=>c.imported).map(c=>({...c,hidden:true,manualOverride:true}))})}>Clear annotations</button> {error && <span role="alert">{error}</span>}
  </details>;
}
