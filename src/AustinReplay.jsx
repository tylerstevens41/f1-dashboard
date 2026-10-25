
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const DATA_URL = "/data/austin-2026-race.json";
const STORAGE_KEY = "austin-2026-track-markers";

const TRACK_PADDING = 900;
const MARKER_RADIUS = 350;
const MAX_INTERPOLATION_GAP_MS = 5000;

function formatClock(ms) {
  const seconds = Math.floor(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;

  return [
    hours,
    String(minutes).padStart(2, "0"),
    String(remainder).padStart(2, "0"),
  ].join(":");
}

function getTime(value) {
  return Date.parse(value);
}

function latestAt(records, time) {
  if (!records?.length) return null;

  let low = 0;
  let high = records.length - 1;
  let result = -1;

  while (low <= high) {
    const mid = (low + high) >> 1;

    if (getTime(records[mid].date) <= time) {
      result = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return result >= 0 ? records[result] : null;
}

function interpolateLocation(points, time) {
  if (!points?.length) return null;

  let low = 0;
  let high = points.length - 1;

  while (low <= high) {
    const mid = (low + high) >> 1;

    if (points[mid][0] < time) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  const next = points[low];
  const previous = points[low - 1];

  if (!previous) {
    return next && next[0] - time < 2000
      ? { x: next[1], y: next[2] }
      : null;
  }

  if (!next) {
    return time - previous[0] < 3000
      ? { x: previous[1], y: previous[2] }
      : null;
  }

  const gap = next[0] - previous[0];

  if (
    gap <= 0 ||
    gap > MAX_INTERPOLATION_GAP_MS
  ) {
    return time - previous[0] < 2000
      ? { x: previous[1], y: previous[2] }
      : null;
  }

  const fraction = Math.max(
    0,
    Math.min(1, (time - previous[0]) / gap)
  );

  return {
    x:
      previous[1] +
      (next[1] - previous[1]) * fraction,
    y:
      previous[2] +
      (next[2] - previous[2]) * fraction,
  };
}

function makeTrack(reference) {
  if (!reference?.length) return null;

  const xs = reference.map((p) => p.x);
  const ys = reference.map((p) => p.y);

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  const project = (x, y) => ({
    x: x - minX + TRACK_PADDING,
    y: maxY - y + TRACK_PADDING,
  });

  const points = reference.map((p) =>
    project(p.x, p.y)
  );

  const path = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`
    )
    .join(" ");

  return {
    path,
    points,
    project,
    width: maxX - minX + TRACK_PADDING * 2,
    height: maxY - minY + TRACK_PADDING * 2,
  };
}

function loadSavedMarkers() {
  try {
    return JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "[]"
    );
  } catch {
    return [];
  }
}

function findNearestTrackPoint(track, x, y) {
  let nearest = null;
  let distance = Infinity;

  track.points.forEach((point, index) => {
    const d = Math.hypot(
      point.x - x,
      point.y - y
    );

    if (d < distance) {
      distance = d;
      nearest = { ...point, index };
    }
  });

  return nearest;
}

export default function AustinReplay() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [elapsed, setElapsed] = useState(0);
  const [selectedDriver, setSelectedDriver] =
    useState(null);

  const [editMode, setEditMode] = useState("view");
  const [markers, setMarkers] =
    useState(loadSavedMarkers);

  const [cornerNumber, setCornerNumber] =
    useState(1);

  const svgRef = useRef(null);
  const playbackRef = useRef({
    elapsed: 0,
    playing: false,
    speed: 5,
    duration: 0,
  });

  useEffect(() => {
    let cancelled = false;

    fetch(DATA_URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Replay file not found (${response.status}). ` +
            "Run the download script first."
          );
        }

        return response.json();
      })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const startTime = data
    ? getTime(data.metadata.date_start)
    : 0;

  const endTime = data
    ? getTime(data.metadata.date_end)
    : 0;

  const duration = Math.max(
    0,
    endTime - startTime
  );

  const track = useMemo(
    () => makeTrack(data?.reference),
    [data]
  );

  useEffect(() => {
    playbackRef.current = {
      elapsed,
      playing,
      speed,
      duration,
    };
  }, [elapsed, playing, speed, duration]);

  // Continuous clock; GPS interpolation happens
  // at the current playback timestamp.
  useEffect(() => {
    let frame;
    let previousTime;

    function animate(now) {
      if (previousTime === undefined) {
        previousTime = now;
      }

      const delta = Math.min(
        now - previousTime,
        100
      );

      previousTime = now;

      const state = playbackRef.current;

      if (state.playing && state.duration > 0) {
        const next = Math.min(
          state.duration,
          state.elapsed + delta * state.speed
        );

        playbackRef.current.elapsed = next;
        setElapsed(next);

        if (next >= state.duration) {
          playbackRef.current.playing = false;
          setPlaying(false);
        }
      }

      frame = requestAnimationFrame(animate);
    }

    frame = requestAnimationFrame(animate);

    return () => cancelAnimationFrame(frame);
  }, []);

  const time = startTime + elapsed;

  const positionByDriver = useMemo(() => {
    const grouped = {};

    for (const item of data?.positions ?? []) {
      const key = String(item.driver_number);
      (grouped[key] ??= []).push(item);
    }

    for (const records of Object.values(grouped)) {
      records.sort(
        (a, b) => getTime(a.date) - getTime(b.date)
      );
    }

    return grouped;
  }, [data]);

  const intervalsByDriver = useMemo(() => {
    const grouped = {};

    for (const item of data?.intervals ?? []) {
      const key = String(item.driver_number);
      (grouped[key] ??= []).push(item);
    }

    for (const records of Object.values(grouped)) {
      records.sort(
        (a, b) => getTime(a.date) - getTime(b.date)
      );
    }

    return grouped;
  }, [data]);

  const cars = useMemo(() => {
    if (!data || !track) return [];

    return data.drivers.map((driver) => {
      const number = String(driver.driver_number);

      const location = interpolateLocation(
        data.locations[number],
        time
      );

      const projected = location
        ? track.project(location.x, location.y)
        : null;

      const position = latestAt(
        positionByDriver[number],
        time
      );

      const interval = latestAt(
        intervalsByDriver[number],
        time
      );

      return {
        ...driver,
        number,
        point: projected,
        position: position?.position ?? 999,
        gap: interval?.gap_to_leader ?? null,
        interval: interval?.interval ?? null,
        color: `#${driver.team_colour || "FFFFFF"}`,
      };
    }).sort(
      (a, b) =>
        a.position - b.position ||
        Number(a.number) - Number(b.number)
    );
  }, [
    data,
    track,
    time,
    positionByDriver,
    intervalsByDriver,
  ]);

  const currentFlag = useMemo(() => {
    if (!data) return "GREEN";

    const events = data.raceControl
      .filter(
        (event) =>
          getTime(event.date) <= time &&
          event.category === "Flag" &&
          event.scope === "Track"
      )
      .sort(
        (a, b) =>
          getTime(a.date) - getTime(b.date)
      );

    return events.at(-1)?.flag ?? "GREEN";
  }, [data, time]);

  function handleTrackClick(event) {
    if (editMode === "view" || !track) {
      return;
    }

    const svg = svgRef.current;
    const point = svg.createSVGPoint();

    point.x = event.clientX;
    point.y = event.clientY;

    const matrix = svg.getScreenCTM();

    if (!matrix) return;

    const local = point.matrixTransform(
      matrix.inverse()
    );

    const nearest = findNearestTrackPoint(
      track,
      local.x,
      local.y
    );

    if (!nearest) return;

    const marker = {
      id: `${Date.now()}-${Math.random()}`,
      type: editMode,
      x: nearest.x,
      y: nearest.y,
      trackIndex: nearest.index,
      label:
        editMode === "corner"
          ? `T${cornerNumber}`
          : editMode === "drs-start"
          ? "DRS START"
          : "DRS END",
    };

    const next = [...markers, marker];

    setMarkers(next);
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(next)
    );

    if (editMode === "corner") {
      setCornerNumber((value) => value + 1);
    }
  }

  function clearMarkers() {
    if (
      !window.confirm(
        "Remove all saved track markers?"
      )
    ) {
      return;
    }

    setMarkers([]);
    setCornerNumber(1);
    localStorage.removeItem(STORAGE_KEY);
  }

  if (error) {
    return (
      <div style={styles.message}>
        {error}
      </div>
    );
  }

  if (!data || !track) {
    return (
      <div style={styles.message}>
        Loading Austin replay...
      </div>
    );
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div>
          <h2 style={{ margin: 0 }}>
            United States Grand Prix
          </h2>

          <div style={styles.muted}>
            2026 · Austin · Historical Replay
          </div>
        </div>

        <div style={styles.status}>
          {currentFlag}
        </div>
      </header>

      <div style={styles.layout}>
        {/* TIMING TOWER */}
        <aside style={styles.tower}>
          <div style={styles.panelTitle}>
            REPLAY TIMING
          </div>

          <div style={styles.towerRows}>
            {cars.map((car) => {
              const selected =
                selectedDriver === car.number;

              return (
                <div
                  key={car.number}
                  onClick={() =>
                    setSelectedDriver(car.number)
                  }
                  style={{
                    ...styles.driverRow,
                    background: selected
                      ? "#252b36"
                      : "transparent",
                  }}
                >
                  <span style={styles.position}>
                    {car.position === 999
                      ? "—"
                      : car.position}
                  </span>

                  <span
                    style={{
                      ...styles.driverName,
                      borderLeft:
                        `4px solid ${car.color}`,
                    }}
                  >
                    {car.name_acronym}
                  </span>

                  <span style={styles.gap}>
                    {car.position === 1
                      ? "LEADER"
                      : car.gap ?? "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </aside>

        {/* CIRCUIT */}
        <section style={styles.circuitPanel}>
          <div style={styles.panelTitle}>
            CIRCUIT OF THE AMERICAS
          </div>

          <svg
            ref={svgRef}
            viewBox={
              `0 0 ${track.width} ${track.height}`
            }
            preserveAspectRatio="xMidYMid meet"
            onClick={handleTrackClick}
            style={{
              width: "100%",
              height: 540,
              cursor:
                editMode === "view"
                  ? "default"
                  : "crosshair",
            }}
          >
            {/* Track outline */}
            <path
              d={track.path}
              fill="none"
              stroke="#2a303a"
              strokeWidth="350"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            <path
              d={track.path}
              fill="none"
              stroke="#e5e8ee"
              strokeWidth="155"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Editable track markers */}
            {markers.map((marker) => (
              <g
                key={marker.id}
                transform={
                  `translate(${marker.x} ${marker.y})`
                }
                pointerEvents="none"
              >
                <circle
                  r="165"
                  fill={
                    marker.type === "corner"
                      ? "#e10600"
                      : "#1dd58a"
                  }
                  stroke="#0b0d12"
                  strokeWidth="35"
                />

                <text
                  textAnchor="middle"
                  y="-245"
                  fontSize="220"
                  fontWeight="800"
                  fill="#ffffff"
                  stroke="#0b0d12"
                  strokeWidth="35"
                  paintOrder="stroke"
                >
                  {marker.label}
                </text>
              </g>
            ))}

            {/* Driver markers */}
            {cars
              .filter((car) => car.point)
              .map((car) => {
                const selected =
                  selectedDriver === car.number;

                return (
                  <g
                    key={car.number}
                    transform={
                      `translate(${car.point.x} ${car.point.y})`
                    }
                    onClick={(event) => {
                      if (editMode !== "view") return;

                      event.stopPropagation();
                      setSelectedDriver(car.number);
                    }}
                    style={{ cursor: "pointer" }}
                  >
                    {selected && (
                      <circle
                        r="610"
                        fill={car.color}
                        opacity="0.2"
                      />
                    )}

                    <circle
                      r={
                        selected
                          ? MARKER_RADIUS + 80
                          : MARKER_RADIUS
                      }
                      fill={car.color}
                      stroke="#0b0d12"
                      strokeWidth="45"
                    />

                    <circle
                      r="75"
                      fill="#ffffff"
                    />

                    <g transform="translate(0 -650)">
                      <rect
                        x="-540"
                        y="-180"
                        width="1080"
                        height="360"
                        rx="60"
                        fill="#10141c"
                        stroke={car.color}
                        strokeWidth="22"
                      />

                      <text
                        x="0"
                        y="25"
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fontSize="280"
                        fontWeight="800"
                        fill="#ffffff"
                      >
                        {car.name_acronym}
                      </text>
                    </g>
                  </g>
                );
              })}
          </svg>

          {/* TRACK EDITOR */}
          <div style={styles.editor}>
            <strong>TRACK EDITOR</strong>

            <select
              value={editMode}
              onChange={(event) =>
                setEditMode(event.target.value)
              }
              style={styles.select}
            >
              <option value="view">
                View / Select Drivers
              </option>

              <option value="corner">
                Place Corner
              </option>

              <option value="drs-start">
                Place DRS Start
              </option>

              <option value="drs-end">
                Place DRS End
              </option>
            </select>

            {editMode === "corner" && (
              <label>
                Corner number{" "}
                <input
                  type="number"
                  min="1"
                  value={cornerNumber}
                  onChange={(event) =>
                    setCornerNumber(
                      Number(event.target.value)
                    )
                  }
                  style={styles.numberInput}
                />
              </label>
            )}

            <button
              onClick={clearMarkers}
              style={styles.button}
            >
              Clear Markers
            </button>
          </div>

          <div style={styles.hint}>
            Choose an editing mode, then click
            near the track. Markers snap to the
            nearest recorded track point and
            are saved in this browser.
          </div>
        </section>
      </div>

      {/* PLAYBACK CONTROLS */}
      <footer style={styles.playback}>
        <button
          onClick={() =>
            setPlaying((value) => !value)
          }
          style={styles.playButton}
        >
          {playing ? "PAUSE" : "PLAY"}
        </button>

        <span style={styles.clock}>
          {formatClock(elapsed)}
        </span>

        <input
          type="range"
          min="0"
          max={duration}
          step="1000"
          value={elapsed}
          onChange={(event) =>
            setElapsed(Number(event.target.value))
          }
          style={{ flex: 1 }}
        />

        <span style={styles.clock}>
          {formatClock(duration)}
        </span>

        <select
          value={speed}
          onChange={(event) =>
            setSpeed(Number(event.target.value))
          }
          style={styles.select}
        >
          {[1, 2, 5, 10, 20].map((value) => (
            <option key={value} value={value}>
              {value}×
            </option>
          ))}
        </select>
      </footer>
    </div>
  );
}

const styles = {
  page: {
    color: "#ffffff",
    background: "#080a0f",
    minHeight: "100vh",
    padding: 16,
    boxSizing: "border-box",
  },

  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 14,
  },

  muted: {
    color: "#98a1b0",
    fontSize: 12,
    marginTop: 5,
  },

  status: {
    padding: "7px 12px",
    background: "#252b36",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 800,
  },

  layout: {
    display: "grid",
    gridTemplateColumns:
      "minmax(280px, 32%) minmax(0, 1fr)",
    gap: 14,
    alignItems: "start",
  },

  tower: {
    background: "#10131a",
    borderRadius: 10,
    overflow: "hidden",
  },

  panelTitle: {
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: 1,
    padding: "13px 15px",
    borderBottom: "1px solid #292e39",
  },

  towerRows: {
    padding: "4px 0",
  },

  driverRow: {
    height: 27,
    display: "grid",
    gridTemplateColumns: "34px 1fr 85px",
    alignItems: "center",
    padding: "0 10px",
    gap: 7,
    fontSize: 11,
    borderBottom: "1px solid #232732",
    cursor: "pointer",
  },

  position: {
    color: "#d7dce5",
    fontWeight: 700,
  },

  driverName: {
    paddingLeft: 9,
    fontWeight: 800,
  },

  gap: {
    textAlign: "right",
    color: "#bfc6d1",
    fontVariantNumeric: "tabular-nums",
  },

  circuitPanel: {
    minWidth: 0,
    background: "#10131a",
    borderRadius: 10,
    overflow: "hidden",
  },

  editor: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    alignItems: "center",
    padding: 14,
    borderTop: "1px solid #292e39",
    fontSize: 11,
  },

  select: {
    background: "#1d222c",
    color: "#ffffff",
    border: "1px solid #394151",
    borderRadius: 5,
    padding: "7px 9px",
  },

  numberInput: {
    width: 48,
    background: "#1d222c",
    color: "#ffffff",
    border: "1px solid #394151",
    borderRadius: 5,
    padding: 6,
  },

  button: {
    background: "#303746",
    color: "#ffffff",
    border: 0,
    borderRadius: 5,
    padding: "8px 12px",
    cursor: "pointer",
  },

  hint: {
    color: "#8e98a8",
    padding: "0 14px 14px",
    fontSize: 11,
  },

  playback: {
    display: "flex",
    alignItems: "center",
    gap: 15,
    padding: 15,
    marginTop: 14,
    background: "#10131a",
    borderRadius: 10,
  },

  playButton: {
    background: "#e10600",
    color: "#ffffff",
    border: 0,
    borderRadius: 5,
    padding: "10px 18px",
    fontWeight: 800,
    cursor: "pointer",
  },

  clock: {
    minWidth: 65,
    fontSize: 12,
    fontVariantNumeric: "tabular-nums",
  },

  message: {
    padding: 30,
    color: "#ffffff",
    background: "#10131a",
  },
};
