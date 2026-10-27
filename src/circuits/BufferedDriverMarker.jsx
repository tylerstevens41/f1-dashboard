import { useEffect, useRef } from 'react';

export default function BufferedDriverMarker({ driver, selected, showLabel, onSelect, project, animation }) {
  const marker=useRef(null);
  useEffect(()=>{
    if(!animation)return;
    return animation.subscribe(driver.driver_number, output=>{
      if(!marker.current)return;
      marker.current.style.visibility=output.point ? 'visible':'hidden';
      marker.current.dataset.motionState=output.state;
      if(output.point){
        const p=project(output.point.x,output.point.y);
        if(p)marker.current.setAttribute('transform',`translate(${p.x} ${p.y})`);
      }
    });
  },[animation,driver.driver_number,project]);
  return <g ref={marker} data-driver={driver.driver_number} style={{cursor:'pointer',visibility:'hidden'}} onClick={onSelect}>
    {selected && <circle r="400" fill={driver.color} opacity="0.2" />}
    <circle r={selected?310:260} fill={driver.color} stroke="#0c0e13" strokeWidth="35"/><circle r="45" fill="white"/>
    {showLabel && <g transform="translate(0 -300)"><rect x="-375" y="-125" width="750" height="250" rx="35" fill="#10141c" stroke={driver.color} strokeWidth="18"/>
      <text y="12" textAnchor="middle" dominantBaseline="middle" fontSize="185" fontWeight="800" fill="white">{driver.label}</text></g>}
  </g>;
}
