import { useEffect, useState } from 'react';

function Plot({ rows, fields, title, normalize=false }) {
  const values=rows.flatMap(row=>fields.map(([key])=>normalize?row[key]/row.requestedRate:row[key])).filter(Number.isFinite);
  const min=normalize?0.98:0;
  const max=normalize?1.02:Math.max(1,...values);
  const points=key=>rows.map((row,i)=>{
    const value=normalize?row[key]/row.requestedRate:row[key];
    if(!Number.isFinite(value))return null;
    return `${i/Math.max(1,rows.length-1)*600},${Math.max(0,Math.min(100,100-(value-min)/(max-min)*100))}`;
  }).filter(Boolean).join(' ');
  return <div><strong>{title}</strong><span> ({min.toFixed(2)}–{max.toFixed(2)})</span>
    <svg role="img" aria-label={title} viewBox="0 0 600 105" style={{width:'100%',height:90,background:'#090d14'}}>
      {normalize && <line x1="0" x2="600" y1="50" y2="50" stroke="#555"/>}
      {fields.map(([key,color])=><polyline key={key} points={points(key)} fill="none" stroke={color} strokeWidth="1.5"/>)}
    </svg><div>{fields.map(([key,color])=><span key={key} style={{color,marginRight:10}}>{key}</span>)}</div>
  </div>;
}
function exportTrace(animation){
  const csv=animation.traceCsv();
  if(!csv)return;
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download='f1-animation-trace.csv';anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const number=value=>Number.isFinite(value)?value.toFixed(3):'—';
export default function AnimationDiagnostics({ animation }) {
  const [stats,setStats]=useState(null);
  const [manual,setManual]=useState(false);
  const [buffer,setBuffer]=useState(1000);
  useEffect(()=>{
    const timer=setInterval(()=>setStats(animation.diagnostics(performance.now())),500);
    return()=>{clearInterval(timer);animation.setTracing(false);};
  },[animation]);
  return <details onToggle={e=>animation.setTracing(e.currentTarget.open)} style={{maxHeight:360,overflow:'auto',fontSize:10,padding:8,background:'#151b25'}}>
    <summary>Animation diagnostics</summary>
    <label><input type="checkbox" checked={manual} onChange={e=>{setManual(e.target.checked);animation.setBuffer(e.target.checked?buffer:null);}}/>Manual buffer (source milliseconds; changing it explicitly re-primes)</label>
    <input aria-label="Interpolation buffer" type="range" min="0" max="5000" step="25" value={buffer} disabled={!manual} onChange={e=>{setBuffer(Number(e.target.value));animation.setBuffer(Number(e.target.value));}}/>
    {stats && <>
      <p>Playback: {number(stats.sourceTime)} · Presentation: {number(stats.interpolationTime)} · {stats.running?'running':'paused'} {stats.speed}×</p>
      <p>Actual presentation rate: {number(stats.presentationRate)} · clock rate: {number(stats.clockRate)} · backend rate: {number(stats.serverRate)} · phase error: {number(stats.phaseErrorMs)} ms · correction: {stats.correctionPpm} ppm</p>
      <p>Position delivery: {stats.deliveryHz?.toFixed(1)??'—'} Hz · locked buffer: {stats.bufferMs.toFixed(0)} ms · recommended: {stats.recommendedMs.toFixed(0)} ms · effective delay: {number(stats.effectiveDelayMs)} ms · rebuffers: {stats.rebuffers} · underruns: {stats.underruns}</p>
      <label>Trace driver <select aria-label="Trace driver" onChange={e=>animation.inspect(e.target.value)} defaultValue=""><option value="">First available</option>{stats.drivers.map(d=><option key={d.number} value={d.number}>{d.number}</option>)}</select></label>
      <button onClick={()=>exportTrace(animation)}>Export bounded CSV trace</button>
      <Plot rows={stats.trace} title="Timeline rate / selected playback speed" fields={[["presentationRate","#48dfff"],["clockRate","#ffbd48"]]} normalize/>
      <Plot rows={stats.trace} title="Source-implied and rendered speed (native units/source second)" fields={[["sourcePathSpeed","#48df99"],["renderedPathSpeed","#48dfff"],["renderedChordSpeed","#ffbd48"]]}/>
      <table><thead><tr>{['Driver','Hz','Buffered','Motion','Rejected','Underruns'].map(h=><th key={h}>{h}</th>)}</tr></thead>
        <tbody>{stats.drivers.map(d=><tr key={d.number}><td>{d.number}</td><td>{d.frequencyHz?.toFixed(1)??'—'}</td><td>{d.buffered}</td><td>{d.state}</td><td>{d.rejected}</td><td>{d.underruns}</td></tr>)}</tbody></table>
      <p>Trace records while this panel is open (up to 3,600 frames). Speeds come from GPS chords and timestamps, not validated vehicle telemetry. CSV includes source intervals/repeated coordinates, phase error, rates and buffer measurements. Flat clock rates with pulsing source speeds implicate source sampling; chord/path differences at corners identify polyline effects.</p>
    </>}
  </details>;
}
