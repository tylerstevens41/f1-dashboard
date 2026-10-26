import { useEffect, useRef } from 'react';
import { appendSample, interpolateSamples } from './interpolation';

export default function BufferedDriverMarker({ driver, selected, showLabel, onSelect, project, clockRef, options }) {
  const marker=useRef(null);
  const history=useRef([]);
  useEffect(() => {
    const samples=driver.history?.length ? driver.history : [{x:driver.rawX,y:driver.rawY,time:driver.sampleTime}];
    for(const sample of samples) history.current=appendSample(history.current,sample,options);
  },[driver.rawX,driver.rawY,driver.sampleTime,driver.history,options]);
  useEffect(() => {
    let frame;
    function draw(){
      const clock=clockRef.current;
      const elapsed=clock.running ? Math.min(performance.now()-clock.receivedAt,1000)*clock.speed : 0;
      const latest=history.current.at(-1);
      const sourceAge=latest ? clock.time+elapsed-latest.time : Infinity;
      // Anchor the short buffer to the received source timeline when transport
      // latency exceeds it. This adds 250 ms, rather than guessing future GPS.
      const delay=Math.max(options.delayMs*clock.speed,latest ? clock.time-latest.time+options.delayMs*clock.speed : 0);
      const point=sourceAge>options.staleMs ? null : interpolateSamples(history.current,clock.time+elapsed-delay,options);
      if(marker.current){
        marker.current.style.visibility=point ? 'visible':'hidden';
        if(point){ const p=project(point.x,point.y); marker.current.setAttribute('transform',`translate(${p.x} ${p.y})`); }
      }
      frame=requestAnimationFrame(draw);
    }
    frame=requestAnimationFrame(draw);
    return()=>cancelAnimationFrame(frame);
  },[project,clockRef,options]);
  return <g ref={marker} data-driver={driver.driver_number} style={{cursor:'pointer',visibility:'hidden'}} onClick={onSelect}>
    {selected && <circle r="400" fill={driver.color} opacity="0.2" />}
    <circle r={selected?310:260} fill={driver.color} stroke="#0c0e13" strokeWidth="35"/><circle r="45" fill="white"/>
    {showLabel && <g transform="translate(0 -300)"><rect x="-375" y="-125" width="750" height="250" rx="35" fill="#10141c" stroke={driver.color} strokeWidth="18"/>
      <text y="12" textAnchor="middle" dominantBaseline="middle" fontSize="185" fontWeight="800" fill="white">{driver.label}</text></g>}
  </g>;
}
