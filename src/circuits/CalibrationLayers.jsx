
export function LayerControls({ layers, setLayers }) {
  return <div className="calibration-layer-controls">{[
    ['outline','Calibrated outline'],['raw','Raw GPS samples'],['transformed','Transformed GPS'],
    ['alignedSvg','Aligned original SVG'],['original','Original SVG (unregistered)'],['drivers','Driver markers'],
  ].map(([key,label])=><label key={key}><input type="checkbox" checked={layers[key]} onChange={e=>setLayers({...layers,[key]:e.target.checked})}/>{label}</label>)}</div>;
}

function scatter(points,project,color){
  return points?.map((p,i)=>{const point=project(p[0],p[1]);return point && <circle key={i} cx={point.x} cy={point.y} r="18" fill={color} opacity="0.55"/>;});
}
export default function CalibrationLayers({ calibration, geometry, circuit, layers }) {
  if(!layers)return null;
  const native=geometry.projectNative ?? geometry.project;
  const aligned=calibration?.svgComparison?.similarity.points;
  const path=aligned?.map((p,i)=>{const point=native(p[0],p[1]);return `${i?'L':'M'} ${point.x} ${point.y}`;}).join(' ');
  return <g pointerEvents="none" aria-label="Calibration comparison layers">
    {layers.original && <image href={circuit.decorativeSvg} x="0" y="0" width={geometry.width} height={geometry.height} opacity="0.3" preserveAspectRatio="xMidYMid meet"/>}
    {layers.raw && scatter(calibration?.debug?.raw,native,'#ff8040')}
    {layers.transformed && scatter(calibration?.debug?.accepted,geometry.project,'#40deff')}
    {layers.alignedSvg && path && <path d={path+' Z'} fill="none" stroke="#d68cff" strokeWidth="60" opacity="0.8"/>}
  </g>;
}

