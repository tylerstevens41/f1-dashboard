import AnimationDiagnostics from '../animation/AnimationDiagnostics';
import { useEffect, useMemo, useState, useRef } from 'react';
import CircuitRenderer from './CircuitRenderer';
import CalibrationLayers, { LayerControls } from './CalibrationLayers';
import { calibrationGeometry, validateCalibration } from './calibration';
import { findCircuit } from './registry';
import AnnotationEditor from './AnnotationEditor';
import AppearancePanel from './AppearancePanel';
import { defaultAppearance, emptyAnnotations, geometryId, nearestFraction, validateAnnotations, mergeImportedCorners, placeAnnotation } from './annotations';
import {pointAt} from './geometry';
import {boundaryDisplayAudit,calculatedBoundaryPreview,browserBoundaryAudit,downloadAudit} from './boundaryAudit';
import './live-circuit.css';


export default function LiveCircuitSvg({ animation, circuitName='Austin', mode='LIVE',
  drivers=[], selectedDriver=null, onSelectDriver }) {
  const circuit=findCircuit(circuitName);
  const [loaded,setLoaded]=useState(null);
  const [error,setError]=useState('');
  const [revision,setRevision]=useState(0);
  const [debug,setDebug]=useState(false);
  const [labels,setLabels]=useState(true);
  const [draft,setDraft]=useState(null);
  const [placing,setPlacing]=useState(null);
  const [preview,setPreview]=useState(false);
  const [selection,setSelection]=useState(null);
  const [placementError,setPlacementError]=useState('');
  const [previewCalculated,setPreviewCalculated]=useState(false);
  const [showAuditAnchors,setShowAuditAnchors]=useState(false);
  const circuitSvg=useRef(null);
  const [candidateSectors,setCandidateSectors]=useState(null);
  const [appearance,setAppearance]=useState(()=>{try{return {...defaultAppearance,...JSON.parse(localStorage.getItem('f1-track-appearance')||'{}')};}catch{return defaultAppearance;}});
  const [layers,setLayers]=useState({outline:true,raw:false,transformed:false,alignedSvg:false,original:false,drivers:true});
  useEffect(()=>{ if(animation && circuit) animation.configure(circuit.motion); },[animation,circuit]);
  useEffect(()=>{
    if(!circuit)return;
    const controller=new AbortController();
    async function load(){
      try{
        const reference=await fetch(circuit.sources.livef1.referenceFile,{signal:controller.signal,cache:'no-store'});
        if(!reference.ok)throw new Error('GPS reference unavailable');
        const legacy=await reference.json();
        let calibration=null;
        let warning='';
        const response=await fetch(circuit.calibrationFile,{signal:controller.signal,cache:'no-store'});
        if(response.ok && response.headers.get('content-type')?.includes('json')){
          try{calibration=validateCalibration(await response.json(),circuit.id,circuit.layoutVersion);}
          catch(err){warning=`Invalid calibration: ${err.message}. Using unverified legacy reference.`;}
        }else if(response.status!==404 && response.headers.get('content-type')?.includes('json')){
          warning=`Calibration unavailable (HTTP ${response.status}); using unverified legacy reference.`;
        }
        let annotationFile=null;
        const ar=await fetch(circuit.annotationFile,{signal:controller.signal,cache:'no-store'});
        if(ar.ok && ar.headers.get('content-type')?.includes('json')) {
          try {annotationFile=await ar.json();} catch {warning='Annotation JSON is invalid; circuit remains unconfigured.';}
        }
        let cornerFile=null;
        try {
          const cr=await fetch(circuit.cornerFile,{signal:controller.signal,cache:'no-store'});
          if(cr.ok && cr.headers.get('content-type')?.includes('json')) cornerFile=await cr.json();
        } catch(err) {if(err.name==='AbortError')throw err;warning='Imported corner file is invalid or unavailable.';}
        let sectorFile=null;
        try {
          const sr=await fetch(circuit.sectorFile,{signal:controller.signal,cache:'no-store'});
          if(sr.ok && sr.headers.get('content-type')?.includes('json')) sectorFile=await sr.json();
        }catch(err){if(err.name==='AbortError')throw err;warning='Calculated sector file is invalid or unavailable.';}
        if(!controller.signal.aborted){setLoaded({legacy:legacy.points,calibration,annotationFile,cornerFile,sectorFile});setError(warning);}
      }catch(err){if(err.name!=='AbortError')setError(err.message);}
    }
    load();return()=>controller.abort();
  },[circuit,revision]);
  const geometry=useMemo(()=>loaded?calibrationGeometry(loaded.calibration,loaded.legacy):null,[loaded]);
  const annotations=useMemo(()=>{
    if(!geometry || !circuit)return null;
    const id=geometryId(geometry);
    let base=emptyAnnotations(circuit,geometry);
    try {if(loaded?.cornerFile)base=validateAnnotations(loaded.cornerFile,circuit,geometry);} catch(err) {base.loadError=err.message;}
    try {if(candidateSectors||loaded?.sectorFile){const sectors=validateAnnotations(candidateSectors??loaded.sectorFile,circuit,geometry);base=mergeImportedCorners(sectors,{...base,startFinish:base.startFinish??sectors.startFinish,sector1End:base.sector1End??sectors.sector1End,sector2End:base.sector2End??sectors.sector2End,direction:sectors.direction});}} catch(err) {base.loadError=err.message;}
    try {if(loaded?.annotationFile)base=mergeImportedCorners(base,validateAnnotations(loaded.annotationFile,circuit,geometry));} catch(err) {base.loadError=err.message;}
    if(draft?.geometryId===id && draft?.circuitId===circuit.id && draft?.layoutVersion===circuit.layoutVersion)return mergeImportedCorners(base,draft);
    if(import.meta.env.DEV){try{const saved=JSON.parse(localStorage.getItem(`f1-annotations-${circuit.id}-${circuit.layoutVersion}-${id}`)||'null');if(saved)return mergeImportedCorners(base,validateAnnotations(saved,circuit,geometry));}catch{ /* incompatible drafts are never applied */ }}
    return base;
  },[geometry,circuit,draft,loaded,candidateSectors]);
  const displayAnnotations=useMemo(()=>import.meta.env.DEV && previewCalculated && annotations?calculatedBoundaryPreview(annotations):annotations,[previewCalculated,annotations]);
  const auditRows=useMemo(()=>{
    if(!annotations||!geometry)return [];
    let saved=null;
    if(import.meta.env.DEV){try{saved=JSON.parse(localStorage.getItem(`f1-annotations-${circuit.id}-${circuit.layoutVersion}-${annotations.geometryId}`)||'null');}catch{ /* optional */ }}
    return boundaryDisplayAudit(displayAnnotations,geometry,{...loaded,sectorFile:candidateSectors??loaded?.sectorFile,calculatedOrigin:candidateSectors?'candidate-file':'calculated-file',saved,draft:previewCalculated?null:draft});
  },[annotations,displayAnnotations,geometry,circuit,loaded,draft,previewCalculated,candidateSectors]);
  const changeAnnotations=value=>{setPreviewCalculated(false);setPreview(true);setDraft(value);try{localStorage.setItem(`f1-annotations-${circuit.id}-${circuit.layoutVersion}-${value.geometryId}`,JSON.stringify(value));}catch{ /* storage optional */ }};
  const changeAppearance=value=>{setAppearance(value);try{localStorage.setItem('f1-track-appearance',JSON.stringify(value));}catch{ /* storage optional */ }};
  const place=event=>{
    if(!placing||!geometry||!annotations)return;
    event.stopPropagation();
    try {
      const svg=event.currentTarget,point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
      const matrix=svg.getScreenCTM();if(!matrix)throw Error('SVG transform is unavailable');const pos=point.matrixTransform(matrix.inverse());
      const at=nearestFraction(geometry,pos.x,pos.y);
      changeAnnotations(placeAnnotation(annotations,placing,at));
      setSelection(placing);setPlacementError('');setPlacing(null);
    } catch(err) {setPlacementError(err.message);}

  };
  const markers=useMemo(()=>{
    if(!geometry)return [];
    return drivers.flatMap(driver=>{
      const gps=driver.gps;
      if(!gps || !Number.isFinite(gps.X)||!Number.isFinite(gps.Y)||!Number.isFinite(gps._sampleTimeMs))return [];
      const point=geometry.project(gps.X,gps.Y);
      const raw=String(driver.team_colour??'FFFFFF').replace('#','');
      return [{...driver,...point,rawX:gps.X,rawY:gps.Y,sampleTime:gps._sampleTimeMs,history:gps._history,
        color:/^[0-9a-f]{6}$/i.test(raw)?`#${raw}`:'#FFFFFF',label:driver.name_acronym??driver.driver_number}];
    });
  },[drivers,geometry]);
  if(!circuit)return <p>No configured circuit for {circuitName}.</p>;
  const calibration=loaded?.calibration;
  const status=calibration?.status??'missing';
  return <div className="live-circuit-shell">
    <div className="live-circuit-toolbar"><strong>{circuit.name}</strong>
      <span className={`calibration-status ${status}`}>Calibration: {status==='candidate'?'unverified candidate':status}</span>
      <label><input type="checkbox" checked={labels} onChange={e=>setLabels(e.target.checked)}/>Labels</label>
      {import.meta.env.DEV && <button aria-pressed={debug} onClick={()=>setDebug(v=>!v)}>GPS calibration overlay</button>}
    </div>
    {import.meta.env.DEV && debug && <div className="calibration-debug-panel">
      <LayerControls layers={layers} setLayers={setLayers}/>
      <p>Orange: raw/native GPS. Cyan: accepted GPS after mapping. Purple: original SVG registered to GPS. Unregistered SVG is a visual comparison only.</p>
      <p>{calibration?`Layout ${calibration.layoutVersion} · ${calibration.svgComparison?.decision} · held-out p95 ${calibration.validation?.heldOut?.p95?.toFixed(1)} feed units`:'No calibration artifact. Run the local collection/build commands; legacy reference is unverified.'}</p>
      <p>Start/finish: {calibration?.startFinish?.status??'not established'}. No car is snapped to this path.</p>
      <button onClick={()=>setRevision(v=>v+1)}>Reload calibration JSON</button>
    </div>}
    {import.meta.env.DEV && geometry && annotations && <><AppearancePanel value={appearance} onChange={changeAppearance} preview={preview} setPreview={setPreview}/><AnnotationEditor circuit={circuit} geometry={geometry} value={annotations} onChange={changeAnnotations} placing={placing} setPlacing={setPlacing} onSelect={setSelection}/><button onClick={()=>setRevision(v=>v+1)}>Reload annotation files</button><div className="calibration-debug-panel">Annotations: {[annotations.startFinish,annotations.sector1End,annotations.sector2End].every(x=>x?.status==='verified')?'verified': 'unverified / incomplete'} · {annotations.corners.length} corners · FastF1 alignment: {annotations.alignment?.status??'not loaded'} · held-out RMS {annotations.alignment?.heldOutRms?.toFixed(1)??'—'}, p95 {annotations.alignment?.heldOutP95?.toFixed(1)??'—'} native units · {placing?'click track to place':''}</div></>}
    {import.meta.env.DEV && animation && <AnimationDiagnostics animation={animation}/>}
    {(placementError||annotations?.loadError) && <p role="alert" className="calibration-error">{placementError||annotations.loadError}</p>}
    {import.meta.env.DEV && annotations?.boundaryDiagnostics && <div className="calibration-debug-panel">Source calculation: provisional · {annotations.boundaryDiagnostics.validLaps} laps / {annotations.boundaryDiagnostics.drivers} drivers · {Object.values(annotations.boundaryDiagnostics.rejected??{}).reduce((a,b)=>a+b,0)} rejected · {annotations.sectorSource?.year} {annotations.sectorSource?.event} {annotations.sectorSource?.session} · FIA: {annotations.boundaryDiagnostics.fia?.status}<br/>{['startFinish','sector1End','sector2End'].map(k=><span key={k}>{k}: {annotations[k]?.at.toFixed(5)??'overridden / hidden'} · p95 {annotations[k]?.sourceEstimate?.statistics?.p95NativeDistance?.toFixed(1)??'—'} native units · {annotations[k]?.sourceEstimate?.statistics?.accepted??'—'} kept / {annotations[k]?.sourceEstimate?.statistics?.outliers??'—'} outliers; </span>)}<br/>{annotations.boundaryDiagnostics.fia?.warnings?.join(' · ')}</div>}
    {import.meta.env.DEV && annotations && geometry && <details className="circuit-dev-panel"><summary>Boundary accuracy and display audit</summary>
      <p>Precision is lap-to-lap spread. Accuracy remains unverified without registered independent physical timing lines. Current file warnings may use older FIA reference values; revalidate locally.</p>
      <label>Load candidate sector JSON (memory only) <input type="file" accept=".json,application/json" onChange={async e=>{
        try {const file=e.target.files?.[0];if(!file)return;if(file.size>16*1024*1024)throw Error('Too large');const data=validateAnnotations(JSON.parse(await file.text()),circuit,geometry);setCandidateSectors(data);setPreviewCalculated(true);setPlacementError('');}
        catch {setPlacementError('Candidate sector file rejected: check JSON schema, circuit, layout and geometry fingerprint.');}
      }}/></label>{candidateSectors && <button onClick={()=>{setCandidateSectors(null);setPreviewCalculated(false);}}>Stop candidate preview</button>}
      <label><input type="checkbox" checked={previewCalculated} onChange={e=>setPreviewCalculated(e.target.checked)}/>Preview calculated boundaries only (does not save or replace overrides)</label>
      <label><input type="checkbox" checked={showAuditAnchors} onChange={e=>setShowAuditAnchors(e.target.checked)}/>Show actual corner anchors and calculated crossings</label>
      {auditRows.map(row=><p key={row.key}>{row.key}: calculated {row.calculatedAt?.toFixed(6)??'missing'} · displayed {row.displayedAt?.toFixed(6)??'hidden'} · {row.origin}{row.different?' · OVERRIDE DIFFERS FROM CALCULATION':''}</p>)}
      <button onClick={()=>downloadAudit(browserBoundaryAudit(displayAnnotations,geometry,auditRows,circuitSvg.current))}>Export safe browser boundary audit</button>
    </details>}
    {error && <p role="alert" className="calibration-error">{error}</p>}
    <div className="live-circuit-viewport">
      {geometry?<CircuitRenderer geometry={geometry} circuit={circuit} drivers={layers.drivers?markers:[]}
        selectedDriver={selectedDriver} onSelectDriver={onSelectDriver} animate animation={animation}
        showLabels={labels} showTrack={!debug||layers.outline} annotations={displayAnnotations} svgRef={circuitSvg} appearance={appearance}
        annotationsCalibrated={true} previewProvisional={import.meta.env.DEV && preview} annotationSelection={selection} editingAnnotations={import.meta.env.DEV && Boolean(placing)} onClick={place}>
        {import.meta.env.DEV && showAuditAnchors && <g pointerEvents="none" data-layer="audit-anchors">
          {annotations.corners.map(c=>{const p=pointAt(geometry,c.at);return <g key={`${c.number}${c.letter??''}`}><circle cx={p.x} cy={p.y} r="50" fill="#ff9f43"/><text x={p.x+70} y={p.y-70} fontSize="140" fill="#ff9f43">anchor {c.number}{c.letter}</text></g>;})}
          {auditRows.filter(r=>r.calculatedPoint).map(r=><g key={r.key}><circle cx={r.calculatedPoint.x} cy={r.calculatedPoint.y} r="110" stroke="#38ffac" fill="none" strokeWidth="25"/><text x={r.calculatedPoint.x+120} y={r.calculatedPoint.y-120} fontSize="150" fill="#38ffac">calculated {r.key}</text></g>)}
        </g>}
        {import.meta.env.DEV && debug && <CalibrationLayers calibration={calibration} geometry={geometry} circuit={circuit} layers={layers}/>}
      </CircuitRenderer>:<p>Loading circuit geometry…</p>}
    </div>
    <div className="live-circuit-bottom">{markers.length} drivers with fresh GPS · {mode} · adaptive timestamp interpolation · {status!=='verified'?'alignment not verified':'validated layout; recheck after event/layout changes'}</div>
  </div>;
}
