
import CircuitRenderer from "./CircuitRenderer";
import { createGeometry } from "./geometry";
import austin from "./tracks/austin";

import {
  useEffect,
  useMemo,
  useState,
} from "react";

// ============================================
// CONFIGURATION
// ============================================

const CIRCUITS = { Austin: austin };

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

function getDriverPosition(driver, clockMs) {
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
      const age = clockMs - parsedTime;

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

// ============================================
// MAIN CIRCUIT COMPONENT
// ============================================

export default function LiveCircuitSvg({
  circuitName = "Austin",
  clockMs,
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
          circuit.sources.livef1.referenceFile
        );

        if (!response.ok) {
          throw new Error(
            `GPS file not found: ${circuit.sources.livef1.referenceFile} (HTTP ${response.status})`
          );
        }

        const contentType =
          response.headers.get("content-type") ?? "";

        if (
          !contentType.includes("json")
        ) {
          throw new Error(
            `Expected JSON at ${circuit.sources.livef1.referenceFile}, but received ${contentType || "unknown content type"}.`
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
    return createGeometry(referencePoints, { matrix: circuit?.sources.livef1.matrix });
  }, [referencePoints, circuit]);

  // Convert incoming driver positions into SVG space.
  const driverMarkers = useMemo(() => {
    if (!map) return [];

    return drivers
      .map((driver) => {
        const gps = getDriverPosition(driver, clockMs);

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
  }, [drivers, map, clockMs]);

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
          <CircuitRenderer geometry={map} circuit={circuit} drivers={showDrivers ? driverMarkers : []}
            selectedDriver={selectedDriver} onSelectDriver={onSelectDriver} showLabels={showLabels}
            showReference={showReference} animate />
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
