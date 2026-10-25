
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// ============================================
// CONFIGURATION
// ============================================

const CIRCUITS = {
  Austin: {
    name: "Circuit of the Americas",
    gpsFile: "/circuits/austin-gps-reference.json",
  },
};

// Change these to adjust the appearance.

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


// ============================================
// GPS HELPERS
// ============================================

function isValidPoint(point) {
  return (
    point != null &&
    Number.isFinite(Number(point.x)) &&
    Number.isFinite(Number(point.y))
  );
}

function getBounds(points) {
  const xs = points.map((point) => Number(point.x));
  const ys = points.map((point) => Number(point.y));

  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

function buildMap(points) {
  const validPoints = points.filter(isValidPoint);

  if (validPoints.length < 20) {
    return null;
  }

  const bounds = getBounds(validPoints);

  const width = bounds.maxX - bounds.minX;
  const height = bounds.maxY - bounds.minY;

  if (width <= 0 || height <= 0) {
    return null;
  }

  const padding = SETTINGS.mapPadding;

  // Project live GPS coordinates into SVG space.
  // Flip Y so the circuit appears in the correct
  // orientation relative to the recorded GPS data.
  const project = (x, y) => ({
    x: Number(x) - bounds.minX + padding,
    y: bounds.maxY - Number(y) + padding,
  });

  // Simplify the recorded reference path slightly.
  const simplified = [];

  for (const point of validPoints) {
    const projected = project(point.x, point.y);

    const previous = simplified.at(-1);

    if (previous) {
      const distance = Math.hypot(
        projected.x - previous.x,
        projected.y - previous.y
      );

      if (distance < 25) {
        continue;
      }
    }

    simplified.push(projected);
  }

  const path = simplified
    .map((point, index) => {
      const command = index === 0 ? "M" : "L";

      return `${command} ${point.x} ${point.y}`;
    })
    .join(" ");

  return {
    path,
    width: width + padding * 2,
    height: height + padding * 2,
    project,
  };
}

function getDriverPosition(driver) {
  const gps = driver.gps ?? driver;

  const x = Number(gps.X ?? gps.x);
  const y = Number(gps.Y ?? gps.y);

  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }

  const timestamp =
    gps.Utc ??
    gps.utc ??
    gps.timestamp;

  if (timestamp) {
    const parsedTime = Date.parse(timestamp);

    if (Number.isFinite(parsedTime)) {
      const age = Date.now() - parsedTime;

      if (age > SETTINGS.maxGpsAgeMs) {
        return null;
      }
    }
  }

  return {
    x,
    y,
    status: gps.Status ?? gps.status ?? "",
    timestamp,
  };
}

function getTeamColor(driver) {
  const raw = String(
    driver.team_colour ??
    driver.TeamColour ??
    "FFFFFF"
  ).replace("#", "");

  return /^[0-9a-fA-F]{6}$/.test(raw)
    ? `#${raw}`
    : "#FFFFFF";
}

function getDriverLabel(driver) {
  return (
    driver.name_acronym ??
    driver.Tla ??
    driver.driver_number ??
    "?"
  );
}

// ============================================
// ANIMATED DRIVER MARKER
// ============================================

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

// ============================================
// MAIN CIRCUIT COMPONENT
// ============================================

export default function LiveCircuitSvg({
  circuitName = "Austin",
  drivers = [],
  selectedDriver = null,
  onSelectDriver,
}) {
  const [referencePoints, setReferencePoints] =
    useState([]);

  const [loadError, setLoadError] = useState("");

  const [showDrivers, setShowDrivers] =
    useState(true);

  const [showLabels, setShowLabels] =
    useState(true);

  const [showReference, setShowReference] =
    useState(false);

  const circuit = CIRCUITS[circuitName];

  // Load the recorded Austin GPS reference.
  useEffect(() => {
    if (!circuit) return;

    let cancelled = false;

    async function loadReference() {
      try {
        setLoadError("");
        setReferencePoints([]);

        const response = await fetch(
          circuit.gpsFile
        );

        if (!response.ok) {
          throw new Error(
            `GPS file not found: ${circuit.gpsFile} (HTTP ${response.status})`
          );
        }

        const contentType =
          response.headers.get("content-type") ?? "";

        if (
          !contentType.includes("json")
        ) {
          throw new Error(
            `Expected JSON at ${circuit.gpsFile}, but received ${contentType || "unknown content type"}.`
          );
        }

        const data = await response.json();

        if (!Array.isArray(data.points)) {
          throw new Error(
            "GPS reference has no points array."
          );
        }

        if (!cancelled) {
          setReferencePoints(data.points);
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(error.message);
        }
      }
    }

    loadReference();

    return () => {
      cancelled = true;
    };
  }, [circuit]);

  const map = useMemo(() => {
    return buildMap(referencePoints);
  }, [referencePoints]);

  // Convert incoming driver positions into SVG space.
  const driverMarkers = useMemo(() => {
    if (!map) return [];

    return drivers
      .map((driver) => {
        const gps = getDriverPosition(driver);

        if (!gps) return null;

        const point = map.project(
          gps.x,
          gps.y
        );

        return {
          ...driver,
          ...point,
          color: getTeamColor(driver),
          label: getDriverLabel(driver),
          status: gps.status,
        };
      })
      .filter(Boolean);
  }, [drivers, map]);

  if (!circuit) {
    return (
      <div style={styles.error}>
        No circuit configured for {circuitName}.
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* HEADER */}
      <div style={styles.header}>
        <div>
          <div style={styles.title}>
            {circuit.name}
          </div>

          <div style={styles.subtitle}>
            LIVE GPS CIRCUIT TRACKER
          </div>
        </div>

        <div style={styles.controls}>
          <label style={styles.control}>
            <input
              type="checkbox"
              checked={showDrivers}
              onChange={(event) =>
                setShowDrivers(event.target.checked)
              }
            />
            Drivers
          </label>

          <label style={styles.control}>
            <input
              type="checkbox"
              checked={showLabels}
              onChange={(event) =>
                setShowLabels(event.target.checked)
              }
            />
            Labels
          </label>

          <label style={styles.control}>
            <input
              type="checkbox"
              checked={showReference}
              onChange={(event) =>
                setShowReference(event.target.checked)
              }
            />
            GPS points
          </label>
        </div>
      </div>

      {/* ERROR */}
      {loadError && (
        <div style={styles.error}>
          {loadError}
        </div>
      )}

      {/* LOADING */}
      {!map && !loadError && (
        <div style={styles.loading}>
          Loading circuit geometry...
        </div>
      )}

      {/* CIRCUIT */}
      {map && (
        <div style={styles.mapArea}>
          <svg
            viewBox={`0 0 ${map.width} ${map.height}`}
            preserveAspectRatio="xMidYMid meet"
            style={styles.svg}
            role="img"
            aria-label={`${circuit.name} live GPS map`}
          >
            {/* Outer track border */}
            <path
              d={map.path}
              fill="none"
              stroke="#252b36"
              strokeWidth={SETTINGS.trackOuterWidth}
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Main track */}
            <path
              d={map.path}
              fill="none"
              stroke="#e7eaf0"
              strokeWidth={SETTINGS.trackInnerWidth}
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Track centreline */}
            <path
              d={map.path}
              fill="none"
              stroke="#8b94a4"
              strokeWidth="10"
              strokeDasharray="45 55"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity="0.65"
            />

            {/* Reference GPS samples */}
            {showReference &&
              referencePoints
                .filter(
                  (_, index) => index % 4 === 0
                )
                .map((point, index) => {
                  const projected = map.project(
                    point.x,
                    point.y
                  );

                  return (
                    <circle
                      key={index}
                      cx={projected.x}
                      cy={projected.y}
                      r="24"
                      fill="#46d7ff"
                      opacity="0.75"
                    />
                  );
                })}

            {/* Moving drivers */}
            {showDrivers &&
              driverMarkers.map((driver) => {
                const number = String(
                  driver.driver_number
                );

                return (
                  <AnimatedDriverMarker
                    key={number}
                    driver={driver}
                    selected={
                      number ===
                      String(selectedDriver)
                    }
                    showLabel={showLabels}
                    onSelect={() =>
                      onSelectDriver?.(number)
                    }
                  />
                );
              })}
          </svg>
        </div>
      )}

      {/* FOOTER */}
      <div style={styles.footer}>
        <span>
          {driverMarkers.length} live driver positions
        </span>

        <span>
          {referencePoints.length} reference GPS points
        </span>
      </div>

      {selectedDriver && (
        <div style={styles.selected}>
          Selected driver: #{selectedDriver}
        </div>
      )}

      <div style={styles.note}>
        Live driver markers update from the
        LiveF1 GPS feed. Movement is animated
        between incoming positions.
      </div>
    </div>
  );
}

// ============================================
// STYLES
// ============================================

const styles = {
  container: {
    width: "100%",
    background: "#0b0d12",
    color: "#ffffff",
    borderRadius: 12,
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  },

  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 15,
    padding: 18,
    borderBottom: "1px solid #252932",
  },

  title: {
    fontSize: 17,
    fontWeight: 800,
  },

  subtitle: {
    fontSize: 10,
    color: "#939dad",
    marginTop: 5,
    letterSpacing: 1,
  },

  controls: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
  },

  control: {
    display: "flex",
    alignItems: "center",
    gap: 5,
    fontSize: 11,
    cursor: "pointer",
  },

  mapArea: {
    width: "100%",
    height: 520,
    padding: 20,
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },

  svg: {
    width: "100%",
    height: "100%",
    display: "block",
    overflow: "visible",
  },

  footer: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    padding: "12px 18px",
    borderTop: "1px solid #252932",
    color: "#aab2c0",
    fontSize: 11,
  },

  selected: {
    padding: "8px 18px",
    color: "#ffffff",
    fontSize: 11,
  },

  note: {
    padding: "8px 18px 15px",
    color: "#7d8797",
    fontSize: 10,
    lineHeight: 1.5,
  },

  loading: {
    padding: 50,
    textAlign: "center",
    color: "#aab2c0",
  },

  error: {
    padding: 20,
    color: "#ff7070",
  },
};
