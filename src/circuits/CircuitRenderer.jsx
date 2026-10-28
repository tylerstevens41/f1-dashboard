import BufferedDriverMarker from "./BufferedDriverMarker";
import { pointAt, pathRange } from "./geometry";
import { bases, defaultAppearance, palette, sectorRanges, cornerKey } from "./annotations";

function Segment({ geometry, start, end, color, width = 200 }) {
  const ranges = end < start ? [[start, 1], [0, end]] : [[start, end]];
  return ranges.map(([a,b], i) => <path key={i} d={geometry.path} pathLength="1" fill="none" stroke={color} strokeWidth={width} strokeDasharray={`${b-a} ${1-(b-a)}`} strokeDashoffset={-a} />);
}

export default function CircuitRenderer({ geometry, circuit, drivers = [], selectedDriver, onSelectDriver,
  showLabels = true, showReference = false, animate = false, flag, annotations = circuit.annotations,
  annotationsCalibrated = true, svgRef, onClick, children, style, variant = "live", animation, showTrack = true,
  appearance = defaultAppearance, previewProvisional = false, annotationSelection = null, editingAnnotations = false }) {
  if (!geometry) return null;
  const features = annotationsCalibrated ? annotations : {};
  const modern=features?.schema==='f1-circuit-annotations-v1';
  const verified=modern && [features.startFinish,features.sector1End,features.sector2End].every(x=>x?.status==='verified');
  const calculated=modern && [features.startFinish,features.sector1End,features.sector2End].every(x=>x?.calculated||x?.explicitManualSelection||x?.status==='verified');
  const sectors=modern && (verified||calculated||previewProvisional) ? sectorRanges(features) : null;
  const showFeature=f=>f && (!modern || f.status==='verified' || f.calculated || f.explicitManualSelection || previewProvisional);
  const scale=Math.max(1,Math.min(2,Number(appearance.cornerLabelScale)||defaultAppearance.cornerLabelScale));
  const radius=155*scale;
  const spacing=Math.max(0.8,Math.min(1.5,Number(appearance.cornerLabelSpacing)||defaultAppearance.cornerLabelSpacing));
  const cornerLabels=appearance.corners ? (features.corners??[]).filter(f=>!f.hidden && (showFeature(f)||f.imported)).map(f=>{
    const p=pointAt(geometry,f.at);
    return {feature:f,x:p.x+(f.offset?.x??0)*spacing,y:p.y+(f.offset?.y??-450)*spacing};
  }) : [];
  // Expand only the viewport when needed; anchors, offsets and GPS are unchanged.
  const inset=radius+35*scale/2+20;
  const left=Math.min(0,...cornerLabels.map(p=>p.x-inset)),top=Math.min(0,...cornerLabels.map(p=>p.y-inset));
  const right=Math.max(geometry.width,...cornerLabels.map(p=>p.x+inset)),bottom=Math.max(geometry.height,...cornerLabels.map(p=>p.y+inset));
  return <svg ref={svgRef} viewBox={`${left} ${top} ${right-left} ${bottom-top}`} preserveAspectRatio="xMidYMid meet"
    style={style ?? { width: "100%", height: "100%", display: "block", overflow: "visible" }} role="img" aria-label={`${circuit.name} circuit`} onClick={editingAnnotations?undefined:onClick} onClickCapture={editingAnnotations?onClick:undefined}>
    {showTrack && <g data-layer="track">
      {flag && circuit.flagColors[flag] && <path data-layer="race-control" d={geometry.path} fill="none" stroke={circuit.flagColors[flag]} strokeWidth={appearance.trackWidth+100} strokeLinecap="round" strokeLinejoin="round"/>}
      {appearance.drs && (features.zones??[]).filter(showFeature).map(zone=><Segment key={zone.id} geometry={geometry} {...zone} color="#1dd58a" width={appearance.trackWidth+140}/>)}
      <path d={geometry.path} fill="none" stroke="#858d9b" strokeWidth={appearance.trackWidth+40} strokeLinecap="round" strokeLinejoin="round" />
      <path d={geometry.path} fill="none" stroke={bases[appearance.base]??bases.charcoal} strokeWidth={appearance.trackWidth} strokeLinecap="round" strokeLinejoin="round" />
      {sectors ? sectors.flatMap((ranges,index)=>ranges.map(([a,b],i)=><path key={`${index}-${i}`} data-sector={index+1} data-start={a} data-end={b} d={pathRange(geometry,a,b)} fill="none" stroke={palette[index]} strokeWidth={appearance.lineWidth} strokeLinecap="butt" strokeLinejoin="round"/>)) : <path d={geometry.path} fill="none" stroke="#c6ccd5" strokeWidth={appearance.lineWidth} strokeLinecap="round" strokeLinejoin="round"/>}
    </g>}
    {appearance.pitLane && features.pitLane?.path && showFeature(features.pitLane) && <path data-layer="pit-lane" d={features.pitLane.path} fill="none" stroke="#999" strokeWidth="75"/>}
    {appearance.drs && (features.detectionPoints??[]).filter(showFeature).map((f,i)=>{const p=pointAt(geometry,f.at);return <circle data-layer="detection" key={i} cx={p.x} cy={p.y} r="60" fill="#1dd58a"/>;})}
    {appearance.speedTraps && (features.speedTraps??[]).filter(showFeature).map((f,i)=>{const p=pointAt(geometry,f.at);return <text data-layer="speed-trap" key={i} x={p.x} y={p.y-220} fill="white" fontSize="180">{f.label??'SPEED'}</text>;})}
    {cornerLabels.map(({feature:f,x,y},i)=>{
      const selected=annotationSelection?.kind==='corner' && cornerKey(annotationSelection)===cornerKey(f);
      const label=modern?cornerKey(f):`T${cornerKey(f)}`;
      return <g data-layer="corner" data-corner={cornerKey(f)} key={i} pointerEvents="none">
        <circle cx={x} cy={y} r={radius} fill="#151a23" stroke={selected?'#ffd43b':'#e4e8ef'} strokeWidth={(selected?35:18)*scale}/>
        <text x={x} y={y} textAnchor="middle" dominantBaseline="central" fontSize={145*scale*Math.min(1,3/label.length)} fill="white">{label}</text>
      </g>;
    })}
    {appearance.boundaries && (modern?[features.sector1End,features.sector2End]:features.sectors??[]).filter(showFeature).map((f,i)=>{const p=pointAt(geometry,f.at);return <g data-layer="sector-boundary" data-at={f.at} key={i} transform={`translate(${p.x} ${p.y}) rotate(${p.angle})`}><line y1="-210" y2="210" stroke="white" strokeWidth="30"/><text x="230" y="-230" transform={`rotate(${-p.angle})`} fill="white" fontSize="160">{f.label??`S${i+1}`}</text></g>;})}
    {appearance.startFinish && showFeature(features.startFinish) && (()=>{const p=pointAt(geometry,features.startFinish.at);return <g data-layer="start-finish" data-at={features.startFinish.at} transform={`translate(${p.x} ${p.y}) rotate(${p.angle})`}><line y1="-230" y2="230" stroke="white" strokeWidth="75"/><line y1="-230" y2="230" stroke="#10141c" strokeWidth="35" strokeDasharray="55 55"/></g>;})()}
    {previewProvisional && annotationSelection && (()=>{
      const f=annotationSelection.kind==='corner'?features.corners?.find(c=>cornerKey(c)===cornerKey(annotationSelection)):features[annotationSelection.kind];
      if(!f)return null;const p=pointAt(geometry,f.at);
      return <circle data-layer="editor-selection" cx={p.x} cy={p.y} r="250" fill="none" stroke="#ffd43b" strokeWidth="35" pointerEvents="none"/>;
    })()}
    {showReference && geometry.points.filter((_,i) => i % 4 === 0).map((p,i) => <circle key={i} cx={p.x} cy={p.y} r="24" fill="#46d7ff" />)}
    {children}
    {drivers.map(driver => {
      const number = String(driver.driver_number ?? driver.number);
      const selected = number === String(selectedDriver);
      if (animate && animation) return <BufferedDriverMarker key={number} driver={driver} selected={selected} showLabel={showLabels} onSelect={() => onSelectDriver?.(number)} project={geometry.project} animation={animation} />;
      const radius = variant === "replay" ? 350 : 260;
      return <g key={number} transform={`translate(${driver.x} ${driver.y})`} onClick={event => { if (onSelectDriver) { event.stopPropagation(); onSelectDriver(number); } }} style={{ cursor: "pointer" }}>
        {selected && <circle r="610" fill={driver.color} opacity="0.2" />}
        <circle r={radius + (selected ? 80 : 0)} fill={driver.color} stroke="#0b0d12" strokeWidth="45" /><circle r="75" fill="white" />
        {showLabels && <g transform="translate(0 -650)"><rect x="-540" y="-180" width="1080" height="360" rx="60" fill="#10141c" stroke={driver.color} strokeWidth="22" /><text y="25" textAnchor="middle" dominantBaseline="middle" fontSize="280" fontWeight="800" fill="white">{driver.label}</text></g>}
      </g>;
    })}
  </svg>;
}
