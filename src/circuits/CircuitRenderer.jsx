import BufferedDriverMarker from "./BufferedDriverMarker";
import { pointAt } from "./geometry";

function Segment({ geometry, start, end, color }) {
  const ranges = end < start ? [[start, 1], [0, end]] : [[start, end]];
  return ranges.map(([a,b], i) => <path key={i} d={geometry.path} pathLength="1" fill="none" stroke={color} strokeWidth="200" strokeDasharray={`${b-a} ${1-(b-a)}`} strokeDashoffset={-a} />);
}

export default function CircuitRenderer({ geometry, circuit, drivers = [], selectedDriver, onSelectDriver,
  showLabels = true, showReference = false, animate = false, flag, annotations = circuit.annotations,
  annotationsCalibrated = true, svgRef, onClick, children, style, variant = "live", animation, showTrack = true }) {
  if (!geometry) return null;
  const color = circuit.flagColors[flag] ?? "#e7eaf0";
  const features = annotationsCalibrated ? annotations : {};
  return <svg ref={svgRef} viewBox={`0 0 ${geometry.width} ${geometry.height}`} preserveAspectRatio="xMidYMid meet"
    style={style ?? { width: "100%", height: "100%", display: "block", overflow: "visible" }} role="img" aria-label={`${circuit.name} circuit`} onClick={onClick}>
    {showTrack && <g>
    <path d={geometry.path} fill="none" stroke="#252b36" strokeWidth={variant === "replay" ? 350 : 330} strokeLinecap="round" strokeLinejoin="round" />
    <path d={geometry.path} fill="none" stroke={color} strokeWidth={variant === "replay" ? 155 : 160} strokeLinecap="round" strokeLinejoin="round" />
    {variant === "live" && <path d={geometry.path} fill="none" stroke="#8b94a4" strokeWidth="10" strokeDasharray="45 55" opacity="0.65" />}
    </g>}
    {features.zones?.map(zone => <Segment key={zone.id} geometry={geometry} {...zone} color="#1dd58a" />)}
    {[...(features.corners ?? []).map(c => ({ ...c, label: `T${c.number}` })), ...(features.detectionPoints ?? []), ...(features.sectors ?? []), ...(features.startFinish ? [features.startFinish] : [])].map((feature, i) => {
      const p = pointAt(geometry, feature.at);
      return <g key={i} transform={`translate(${p.x} ${p.y})`} pointerEvents="none">
        <circle r="70" fill="#1dd58a" /><text x={feature.offset?.x ?? 0} y={feature.offset?.y ?? -245} textAnchor="middle" fontSize="220" fill="white" stroke="#0b0d12" strokeWidth="25" paintOrder="stroke">{feature.label}</text>
        {feature === features.startFinish && <line x1="0" y1="-150" x2="0" y2="150" stroke="white" strokeWidth="50" transform={`rotate(${p.angle})`} />}
      </g>;
    })}
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
