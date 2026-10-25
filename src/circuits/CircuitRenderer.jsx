import { useEffect, useRef } from "react";
import { pointAt } from "./geometry";

const SETTINGS = {
  mapPadding: 650,

  // Much larger driver markers
  markerRadius: 260,
  selectedMarkerRadius: 310,
  markerBorderWidth: 35,

  // Larger driver labels
  labelWidth: 750,
  labelHeight: 250,
  labelFontSize: 185,

  // Longer smoothing interval
  animationDuration: 3000,

  maxGpsAgeMs: 20000,
  maxJumpDistance: 3000,

  trackOuterWidth: 330,
  trackInnerWidth: 160,
};


function AnimatedDriverMarker({
  driver,
  selected,
  showLabel,
  onSelect,
}) {
  const markerRef = useRef(null);

  const currentRef = useRef({
    x: driver.x,
    y: driver.y,
  });

  const lastAcceptedRef = useRef({
    x: driver.x,
    y: driver.y,
  });

  useEffect(() => {
    const target = {
      x: driver.x,
      y: driver.y,
    };

    const lastAccepted = lastAcceptedRef.current;

    const jumpDistance = Math.hypot(
      target.x - lastAccepted.x,
      target.y - lastAccepted.y
    );

    // Ignore a large isolated jump.
    // This is a basic safeguard, not a complete
    // GPS validation algorithm.
    if (
      jumpDistance > SETTINGS.maxJumpDistance
    ) {
      return;
    }

    lastAcceptedRef.current = target;

    const startPosition = {
      ...currentRef.current,
    };

    const startTime = performance.now();
    const duration = SETTINGS.animationDuration;

    let animationFrame;

    function animate(now) {
      const elapsed = now - startTime;

      const progress = Math.min(
        elapsed / duration,
        1
      );

      // Smoothstep easing
      const eased = progress;

      const x =
        startPosition.x +
        (target.x - startPosition.x) * eased;

      const y =
        startPosition.y +
        (target.y - startPosition.y) * eased;

      currentRef.current = { x, y };

      if (markerRef.current) {
        markerRef.current.setAttribute(
          "transform",
          `translate(${x} ${y})`
        );
      }

      if (progress < 1) {
        animationFrame =
          requestAnimationFrame(animate);
      }
    }

    animationFrame =
      requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animationFrame);
    };
  }, [driver.x, driver.y]);

  const markerRadius = selected
    ? SETTINGS.selectedMarkerRadius
    : SETTINGS.markerRadius;

  return (
    <g
      ref={markerRef}
      transform={`translate(${driver.x} ${driver.y})`}
      onClick={onSelect}
      style={{ cursor: "pointer" }}
    >
      {/* Selected driver glow */}
      {selected && (
        <circle
          r="300"
          fill={driver.color}
          opacity="0.2"
        />
      )}

      {/* Team-coloured marker */}
      <circle
        r={markerRadius}
        fill={driver.color}
        stroke="#0c0e13"
        strokeWidth={SETTINGS.markerBorderWidth}
      />

      {/* White marker centre */}
      <circle
        r="45"
        fill="#ffffff"
      />

      {/* Driver abbreviation */}
      {showLabel && (
        <g transform="translate(0 -300)">
          <rect
            x={-SETTINGS.labelWidth / 2}
            y={-SETTINGS.labelHeight / 2}
            width={SETTINGS.labelWidth}
            height={SETTINGS.labelHeight}
            rx="35"
            fill="#10141c"
            stroke={driver.color}
            strokeWidth="18"
          />

          <text
            x="0"
            y="12"
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={SETTINGS.labelFontSize}
            fontWeight="800"
            fill="#ffffff"
          >
            {driver.label}
          </text>
        </g>
      )}
    </g>
  );
}


function Segment({ geometry, start, end, color }) {
  const ranges = end < start ? [[start, 1], [0, end]] : [[start, end]];
  return ranges.map(([a,b], i) => <path key={i} d={geometry.path} pathLength="1" fill="none" stroke={color} strokeWidth="200" strokeDasharray={`${b-a} ${1-(b-a)}`} strokeDashoffset={-a} />);
}

export default function CircuitRenderer({ geometry, circuit, drivers = [], selectedDriver, onSelectDriver,
  showLabels = true, showReference = false, animate = false, flag, annotations = circuit.annotations,
  annotationsCalibrated = true, svgRef, onClick, children, style, variant = "live" }) {
  if (!geometry) return null;
  const color = circuit.flagColors[flag] ?? "#e7eaf0";
  const features = annotationsCalibrated ? annotations : {};
  return <svg ref={svgRef} viewBox={`0 0 ${geometry.width} ${geometry.height}`} preserveAspectRatio="xMidYMid meet"
    style={style ?? { width: "100%", height: "100%", display: "block", overflow: "visible" }} role="img" aria-label={`${circuit.name} circuit`} onClick={onClick}>
    <path d={geometry.path} fill="none" stroke="#252b36" strokeWidth={variant === "replay" ? 350 : 330} strokeLinecap="round" strokeLinejoin="round" />
    <path d={geometry.path} fill="none" stroke={color} strokeWidth={variant === "replay" ? 155 : 160} strokeLinecap="round" strokeLinejoin="round" />
    {variant === "live" && <path d={geometry.path} fill="none" stroke="#8b94a4" strokeWidth="10" strokeDasharray="45 55" opacity="0.65" />}
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
      if (animate) return <AnimatedDriverMarker key={number} driver={driver} selected={selected} showLabel={showLabels} onSelect={() => onSelectDriver?.(number)} />;
      const radius = variant === "replay" ? 350 : 260;
      return <g key={number} transform={`translate(${driver.x} ${driver.y})`} onClick={event => { if (onSelectDriver) { event.stopPropagation(); onSelectDriver(number); } }} style={{ cursor: "pointer" }}>
        {selected && <circle r="610" fill={driver.color} opacity="0.2" />}
        <circle r={radius + (selected ? 80 : 0)} fill={driver.color} stroke="#0b0d12" strokeWidth="45" /><circle r="75" fill="white" />
        {showLabels && <g transform="translate(0 -650)"><rect x="-540" y="-180" width="1080" height="360" rx="60" fill="#10141c" stroke={driver.color} strokeWidth="22" /><text y="25" textAnchor="middle" dominantBaseline="middle" fontSize="280" fontWeight="800" fill="white">{driver.label}</text></g>}
      </g>;
    })}
  </svg>;
}
