import { useEffect, useMemo, useRef, useState } from 'react';
import CircuitRenderer from './CircuitRenderer';
import CalibrationLayers, { LayerControls } from './CalibrationLayers';
import { calibrationGeometry, validateCalibration } from './calibration';
import austin from './tracks/austin';
import './live-circuit.css';

const CIRCUITS={Austin:austin};

export default function LiveCircuitSvg({ circuitName='Austin', clockMs, mode='LIVE', playback='playing', speed=1,
  drivers=[], selectedDriver=null, onSelectDriver }) {
  const circuit=CIRCUITS[circuitName];
  const [loaded,setLoaded]=useState(null);
  const [error,setError]=useState('');
  const [revision,setRevision]=useState(0);
  const [debug,setDebug]=useState(false);
  const [labels,setLabels]=useState(true);
  const [layers,setLayers]=useState({outline:true,raw:false,transformed:false,alignedSvg:false,original:false,drivers:true});
  const clockRef=useRef({time:0,receivedAt:0,running:false,speed:1});
  useEffect(()=>{
    clockRef.current={time:clockMs,receivedAt:performance.now(),running:mode==='LIVE'||playback==='playing',speed:mode==='LIVE'?1:speed};
  },[clockMs,mode,playback,speed]);
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
        if(!controller.signal.aborted){setLoaded({legacy:legacy.points,calibration});setError(warning);}
      }catch(err){if(err.name!=='AbortError')setError(err.message);}
    }
    load();return()=>controller.abort();
  },[circuit,revision]);
  const geometry=useMemo(()=>loaded?calibrationGeometry(loaded.calibration,loaded.legacy):null,[loaded]);
  const markers=useMemo(()=>{
    if(!geometry)return [];
    return drivers.flatMap(driver=>{
      const gps=driver.gps;
      if(!gps || !Number.isFinite(gps.X)||!Number.isFinite(gps.Y)||!Number.isFinite(gps._sampleTimeMs))return [];
      if(clockMs-gps._sampleTimeMs>circuit.motion.staleMs||gps._sampleTimeMs-clockMs>2000)return [];
      const point=geometry.project(gps.X,gps.Y);
      const raw=String(driver.team_colour??'FFFFFF').replace('#','');
      return [{...driver,...point,rawX:gps.X,rawY:gps.Y,sampleTime:gps._sampleTimeMs,history:gps._history,
        color:/^[0-9a-f]{6}$/i.test(raw)?`#${raw}`:'#FFFFFF',label:driver.name_acronym??driver.driver_number}];
    });
  },[drivers,geometry,clockMs,circuit]);
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
    {error && <p role="alert" className="calibration-error">{error}</p>}
    <div className="live-circuit-viewport">
      {geometry?<CircuitRenderer geometry={geometry} circuit={circuit} drivers={layers.drivers?markers:[]}
        selectedDriver={selectedDriver} onSelectDriver={onSelectDriver} animate clockRef={clockRef} motionOptions={circuit.motion}
        showLabels={labels} showTrack={!debug||layers.outline} annotations={calibration ? {...calibration.annotations,startFinish:{...calibration.startFinish,label:'START / FINISH'}} : circuit.annotations}
        annotationsCalibrated={status==='verified'}>
        {import.meta.env.DEV && debug && <CalibrationLayers calibration={calibration} geometry={geometry} circuit={circuit} layers={layers}/>}
      </CircuitRenderer>:<p>Loading circuit geometry…</p>}
    </div>
    <div className="live-circuit-bottom">{markers.length} drivers with fresh GPS · {mode} · 250 ms interpolation buffer · {status!=='verified'?'alignment not verified':'validated layout; recheck after event/layout changes'}</div>
  </div>;
}
