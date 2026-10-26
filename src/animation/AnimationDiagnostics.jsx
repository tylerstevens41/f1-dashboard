import { useEffect, useState } from 'react';

export default function AnimationDiagnostics({ animation }) {
  const [stats,setStats]=useState(null);
  const [manual,setManual]=useState(false);
  const [buffer,setBuffer]=useState(500);
  useEffect(()=>{
    const timer=setInterval(()=>setStats(animation.diagnostics(performance.now())),500);
    return()=>clearInterval(timer);
  },[animation]);
  return <details style={{maxHeight:240,overflow:'auto',fontSize:10,padding:8,background:'#151b25'}}>
    <summary>Animation diagnostics</summary>
    <label><input type="checkbox" checked={manual} onChange={e=>{setManual(e.target.checked);animation.setBuffer(e.target.checked?buffer:null);}}/>Manual buffer (source milliseconds)</label>
    <input aria-label="Interpolation buffer" type="range" min="0" max="5000" step="25" value={buffer} disabled={!manual} onChange={e=>{setBuffer(Number(e.target.value));animation.setBuffer(Number(e.target.value));}}/>
    {stats && <>
      <p>Playback clock: {stats.sourceTime?.toFixed(1)} · Interpolation clock: {stats.interpolationTime?.toFixed(1)} · {stats.running?'running':'paused'} {stats.speed}×</p>
      <p>Position packet delivery: {stats.deliveryHz?.toFixed(1)??'—'} Hz · table Hz measures unique source GPS cadence.</p>
      <p>Buffer: {stats.bufferMs.toFixed(0)} ms source / {(stats.bufferMs/stats.speed).toFixed(0)} ms wall · target {stats.recommendedMs.toFixed(0)} ms · {stats.automatic?'automatic':'manual'} · Underrun episodes: {stats.underruns}</p>
      <table><thead><tr>{['Driver','Hz','Buffered','Motion','Rejected','Underruns'].map(h=><th key={h}>{h}</th>)}</tr></thead>
        <tbody>{stats.drivers.map(d=><tr key={d.number}><td>{d.number}</td><td>{d.frequencyHz?.toFixed(1)??'—'}</td><td>{d.buffered}</td><td>{d.state}</td><td>{d.rejected}</td><td>{d.underruns}</td></tr>)}</tbody></table>
      <p>Waiting holds the last measured point briefly. Recovering/stale hides the marker; no line is drawn across a missing segment.</p>
    </>}
  </details>;
}
