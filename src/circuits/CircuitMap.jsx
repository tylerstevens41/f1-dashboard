
import { useEffect, useMemo, useRef, useState } from "react";
import defaultCircuit from "./tracks/montreal";

const TRACK_WIDTH = 340;
const TRACK_BORDER_WIDTH = 470;
const MARKER_RADIUS = 230;
const MAP_MARGIN = 680;

// ========================================
// START / FINISH LINE
// ========================================

function StartFinishLine({ pathRef, config, mapRotation }) {
  const [geometry, setGeometry] = useState(null);

  useEffect(() => {
    const path = pathRef.current;

    if (!path || !config.show) {
      setGeometry(null);
      return;
    }

    const totalLength = path.getTotalLength();

    if (!Number.isFinite(totalLength) || totalLength <= 0) {
      return;
    }

    const fraction = Math.max(
      0,
      Math.min(1, config.position ?? 0)
    );

    const position = totalLength * fraction;

    const point = path.getPointAtLength(position);

    // Sample the path on either side of the line
    // to determine the direction of travel.
    const sampleDistance = Math.min(120, totalLength * 0.002);

    const before = path.getPointAtLength(
      Math.max(0, position - sampleDistance)
    );

    const after = path.getPointAtLength(
      Math.min(totalLength, position + sampleDistance)
    );

    const angle =
      (Math.atan2(
        after.y - before.y,
        after.x - before.x
      ) *
        180) /
      Math.PI;

    setGeometry({
      x: point.x,
      y: point.y,
      angle,
    });
  }, [pathRef, config]);

  if (!config.show || !geometry) {
    return null;
  }

  const lineWidth = TRACK_WIDTH + 110;
  const lineThickness = 190;
  const checkerSize = config.chequerSize ?? 90;

  return (
    <g
      transform={`translate(${geometry.x} ${geometry.y}) rotate(${geometry.angle})`}
    >
      <defs>
        <pattern
          id="finish-line-checkers"
          width={checkerSize * 2}
          height={checkerSize * 2}
          patternUnits="userSpaceOnUse"
        >
          <rect
            width={checkerSize * 2}
            height={checkerSize * 2}
            fill="#FFFFFF"
          />

          <rect
            width={checkerSize}
            height={checkerSize}
            fill="#111111"
          />

          <rect
            x={checkerSize}
            y={checkerSize}
            width={checkerSize}
            height={checkerSize}
            fill="#111111"
          />
        </pattern>
      </defs>

      {/* Line crosses the circuit perpendicular
          to the direction of travel. */}
      <rect
        x={-lineThickness / 2}
        y={-lineWidth / 2}
        width={lineThickness}
        height={lineWidth}
        fill="url(#finish-line-checkers)"
        stroke="#FFFFFF"
        strokeWidth="12"
      />

      {/* Small indicator beside the circuit */}
      <g
        transform={`translate(0 ${-lineWidth / 2 + 800}) rotate(${-geometry.angle - mapRotation})`}
      >

        <text
          textAnchor="middle"
          dominantBaseline="central"
          fontSize="145"
          fontWeight="bold"
          fill="#FFFFFF"
          stroke="#11151B"
          strokeWidth="35"
          paintOrder="stroke"
        >
          {config.label}
        </text>
      </g>
    </g>
  );
}

// ========================================
// MAIN CIRCUIT MAP
// ========================================

export default function CircuitMap({
  track,
  circuit = defaultCircuit,
  drivers,
  selectedDriver,
  onSelectDriver,
}) {
  const pathRef = useRef(null);

  const layout = useMemo(() => {
    if (!track) return null;

    const width = track.maxX - track.minX;
    const height = track.maxY - track.minY;

    const centerX = track.padding + width / 2;
    const centerY = track.padding + height / 2;

    const rotate =
      circuit.rotation === "auto"
        ? height > width
          ? 90
          : 0
        : Number(circuit.rotation) || 0;

    const rotated = Math.abs(rotate) % 180 === 90;

    const displayWidth = rotated ? height : width;
    const displayHeight = rotated ? width : height;

    return {
      centerX,
      centerY,
      rotate,
      viewBox: [
        centerX - displayWidth / 2 - MAP_MARGIN,
        centerY - displayHeight / 2 - MAP_MARGIN,
        displayWidth + MAP_MARGIN * 2,
        displayHeight + MAP_MARGIN * 2,
      ].join(" "),
    };
  }, [track]);

  if (!track || !layout) return null;

  const [boundary1, boundary2] =
    circuit.sectorBoundaries;

  const sectorSegments = [
    { start: 0, end: boundary1 },
    { start: boundary1, end: boundary2 },
    { start: boundary2, end: 1 },
  ];

  return (
    <svg
      className="live-track-svg"
      viewBox={layout.viewBox}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={`${circuit.name} circuit with coloured sectors and a start finish line`}
    >
      <g
        transform={`rotate(${layout.rotate} ${layout.centerX} ${layout.centerY})`}
      >
        {/* Outer circuit border */}
        <path
          d={track.path}
          fill="none"
          stroke="#303744"
          strokeWidth={TRACK_BORDER_WIDTH}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Sector paths */}
        {sectorSegments.map((sector, index) => {
          const start = sector.start * 100;
          const length = (sector.end - sector.start) * 100;

          return (
            <path
              key={index}
              d={track.path}
              pathLength={100}
              fill="none"
              stroke={circuit.sectorColors[index]}
              strokeWidth={TRACK_WIDTH}
              strokeLinecap="butt"
              strokeLinejoin="round"
              strokeDasharray={`${length} ${100 - length}`}
              strokeDashoffset={-start}
            />
          );
        })}

        {/* Invisible path used to measure
            the start/finish location and angle */}
        <path
          ref={pathRef}
          d={track.path}
          fill="none"
          stroke="none"
        />

        <StartFinishLine
          pathRef={pathRef}
          config={circuit.startFinish}
          mapRotation={layout.rotate}
        />

        {/* Animated driver markers */}
        {drivers.map((driver) => {
          const x =
            driver.position.x -
            track.minX +
            track.padding;

          const y =
            track.maxY -
            driver.position.y +
            track.padding;

          const selected =
            Number(selectedDriver) ===
            Number(driver.driver_number);

          const color = `#${driver.team_colour || "FFFFFF"}`;

          return (
            <g
              key={driver.driver_number}
              transform={`translate(${x} ${y})`}
              opacity={selected ? 1 : 0.8}
              onClick={() =>
                onSelectDriver(driver.driver_number)
              }
              style={{ cursor: "pointer" }}
            >
              {/* Keep markers upright */}
              <g transform={`rotate(${-layout.rotate})`}>
                {selected && (
                  <circle
                    r={MARKER_RADIUS + 95}
                    fill="none"
                    stroke={color}
                    strokeWidth="55"
                    opacity="0.85"
                  />
                )}

                <rect
                  x="-300"
                  y="-610"
                  width="600"
                  height="260"
                  rx="65"
                  fill={color}
                />

                <text
                  x="0"
                  y="-480"
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="180"
                  fontWeight="bold"
                  fill="#111111"
                >
                  {driver.name_acronym}
                </text>

                <circle
                  r={MARKER_RADIUS}
                  fill={color}
                  stroke="#FFFFFF"
                  strokeWidth="40"
                />

                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="180"
                  fontWeight="bold"
                  fill="#FFFFFF"
                >
                  {driver.driver_number}
                </text>
              </g>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
