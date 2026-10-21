
import { useEffect, useMemo, useRef, useState } from "react";
import TimingTower from "./TimingTower";
import "./LiveRace.css";

const DATA = "/data/montreal-2026-race";
const FALLBACK_START = Date.parse("2026-05-24T20:00:00Z");
const MAX_GAP_MS = 12000;

function findPosition(points, timestamp) {
  if (!points?.length) return null;

  if (
    timestamp < points[0].time ||
    timestamp > points[points.length - 1].time
  ) {
    return null;
  }

  let low = 0;
  let high = points.length - 1;

  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (points[mid].time < timestamp) low = mid + 1;
    else high = mid;
  }

  if (points[low].time === timestamp) return points[low];
  if (low === 0) return null;

  const previous = points[low - 1];
  const next = points[low];
  const gap = next.time - previous.time;

  if (gap <= 0 || gap > MAX_GAP_MS) return null;

  const fraction = (timestamp - previous.time) / gap;

  return {
    x: previous.x + (next.x - previous.x) * fraction,
    y: previous.y + (next.y - previous.y) * fraction,
  };
}

function formatClock(milliseconds) {
  const seconds = Math.max(
    0,
    Math.floor(milliseconds / 1000)
  );

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;

  return [hours, minutes, remaining]
    .map((number) => String(number).padStart(2, "0"))
    .join(":");
}

function buildTrack(locations, laps) {
  // Find a representative completed lap from a driver
  // with recorded GPS coordinates.
  const candidates = laps
    .filter(
      (lap) =>
        Number(lap.lap_duration) > 60 &&
        Number(lap.lap_duration) < 180 &&
        Number.isFinite(Date.parse(lap.date_start))
    )
    .sort(
      (a, b) =>
        Number(a.lap_number) - Number(b.lap_number)
    );

  let circuitPoints = [];

  for (const lap of candidates) {
    const points = locations[lap.driver_number];
    if (!points?.length) continue;

    const start = Date.parse(lap.date_start);
    const end =
      start + Number(lap.lap_duration) * 1000;

    const segment = points.filter(
      (point) =>
        point.time >= start && point.time <= end
    );

    if (segment.length >= 45) {
      circuitPoints = segment;
      break;
    }
  }

  if (circuitPoints.length < 20) {
    return null;
  }

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const point of circuitPoints) {
    minX = Math.min(minX, point.x);
    maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y);
    maxY = Math.max(maxY, point.y);
  }

  const padding = 600;

  const path = circuitPoints
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${
          point.x - minX + padding
        } ${maxY - point.y + padding}`
    )
    .join(" ");

  return {
    path,
    minX,
    maxY,
    padding,
    viewBox: `0 0 ${
      maxX - minX + padding * 2
    } ${maxY - minY + padding * 2}`,
  };
}

export default function LiveRace() {
  const [drivers, setDrivers] = useState([]);
  const [locations, setLocations] = useState({});
  const [laps, setLaps] = useState([]);

  const [startTime, setStartTime] = useState(FALLBACK_START);
  const [endTime, setEndTime] = useState(
    FALLBACK_START + 2 * 60 * 60 * 1000
  );

  const [playbackTime, setPlaybackTime] =
    useState(FALLBACK_START);

  const [selectedDriver, setSelectedDriver] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const previousFrame = useRef(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadRace() {
      try {
        const files = [
          "session.json",
          "drivers.json",
          "locations-replay.json",
          "laps.json",
        ];

        const responses = await Promise.all(
          files.map((filename) =>
            fetch(`${DATA}/${filename}`, {
              signal: controller.signal,
            })
          )
        );

        for (let index = 0; index < responses.length; index++) {
          if (!responses[index].ok) {
            throw new Error(
              `Could not load ${files[index]}`
            );
          }
        }

        const [
          sessionData,
          driverData,
          locationData,
          lapData,
        ] = await Promise.all(
          responses.map((response) => response.json())
        );

        const grouped = {};

        for (const point of locationData) {
          const number = Number(point.driver_number);
          const time = Number(point.time);

          if (
            !Number.isFinite(number) ||
            !Number.isFinite(time) ||
            !Number.isFinite(point.x) ||
            !Number.isFinite(point.y)
          ) {
            continue;
          }

          if (!grouped[number]) grouped[number] = [];

          grouped[number].push({
            time,
            x: point.x,
            y: point.y,
          });
        }

        let finalLocationTime = -Infinity;

        for (const points of Object.values(grouped)) {
          points.sort((a, b) => a.time - b.time);

          if (points.length) {
            finalLocationTime = Math.max(
              finalLocationTime,
              points[points.length - 1].time
            );
          }
        }

        if (!Number.isFinite(finalLocationTime)) {
          throw new Error("No valid replay locations found");
        }

        const session = sessionData.find(
          (item) => Number(item.session_key) === 11291
        );

        const sessionStart = Date.parse(
          session?.date_start
        );

        const firstTime = Number.isFinite(sessionStart)
          ? sessionStart
          : FALLBACK_START;

        const uniqueDrivers = Array.from(
          new Map(
            driverData.map((driver) => [
              Number(driver.driver_number),
              driver,
            ])
          ).values()
        );

        if (!controller.signal.aborted) {
          setDrivers(uniqueDrivers);
          setLocations(grouped);
          setLaps(lapData);
          setStartTime(firstTime);
          setEndTime(
            Math.max(firstTime + 1000, finalLocationTime)
          );
          setPlaybackTime(firstTime);

          const firstDriver =
            uniqueDrivers.find(
              (driver) =>
                String(driver.name_acronym).toUpperCase() ===
                "ANT"
            ) || uniqueDrivers[0];

          setSelectedDriver(
            firstDriver?.driver_number ?? null
          );
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    loadRace();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!isPlaying || loading || error) {
      previousFrame.current = null;
      return;
    }

    let frameId;

    function animate(timestamp) {
      if (previousFrame.current === null) {
        previousFrame.current = timestamp;
      }

      const elapsed = Math.min(
        timestamp - previousFrame.current,
        100
      );

      previousFrame.current = timestamp;

      setPlaybackTime((previous) =>
        Math.min(
          endTime,
          previous + elapsed * speed
        )
      );

      frameId = requestAnimationFrame(animate);
    }

    frameId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frameId);
      previousFrame.current = null;
    };
  }, [isPlaying, loading, error, speed, endTime]);

  useEffect(() => {
    if (playbackTime >= endTime) {
      setIsPlaying(false);
    }
  }, [playbackTime, endTime]);

  const track = useMemo(
    () => buildTrack(locations, laps),
    [locations, laps]
  );

  const visibleDrivers = useMemo(
    () =>
      drivers
        .map((driver) => {
          const position = findPosition(
            locations[driver.driver_number],
            playbackTime
          );

          return position
            ? { ...driver, position }
            : null;
        })
        .filter(Boolean),
    [drivers, locations, playbackTime]
  );

  const elapsed = playbackTime - startTime;
  const duration = endTime - startTime;

  return (
    <main className="live-race-page">
      <div className="live-race-header">
        <div>
          <h2>RACE REPLAY</h2>
          <p>2026 Canadian Grand Prix · Montréal</p>
        </div>

        <span className="replay-badge">
          2026 RACE DATA
        </span>
      </div>

      <section className="live-circuit-panel">
        <div className="live-circuit-heading">
          <h3>CIRCUIT GILLES-VILLENEUVE</h3>
          <span>RACE TRACKER</span>
        </div>

        <div className="live-race-content">
          <TimingTower
            drivers={drivers}
            playbackTime={playbackTime}
            selectedDriver={selectedDriver}
            onSelectDriver={setSelectedDriver}
          />

          <div className="live-circuit-area">
            {loading && (
              <p>Loading Montréal race...</p>
            )}

            {error && (
              <p className="live-error">{error}</p>
            )}

            {!loading && !error && !track && (
              <p>Unable to build circuit outline.</p>
            )}

            {!loading && !error && track && (
              <svg
                className="live-track-svg"
                viewBox={track.viewBox}
                preserveAspectRatio="xMidYMid meet"
                role="img"
                aria-label="2026 Canadian Grand Prix track replay"
              >
                <path
                  className="track-outline"
                  d={track.path}
                />

                <path
                  className="track-center"
                  d={track.path}
                />

                {visibleDrivers.map((driver) => {
                  const x =
                    driver.position.x -
                    track.minX +
                    track.padding;

                  const y =
                    track.maxY -
                    driver.position.y +
                    track.padding;

                  const colour = `#${
                    driver.team_colour || "FFFFFF"
                  }`;

                  const selected =
                    Number(selectedDriver) ===
                    Number(driver.driver_number);

                  return (
                    <g
                      key={driver.driver_number}
                      transform={`translate(${x}, ${y})`}
                      opacity={selected ? 1 : 0.65}
                      onClick={() =>
                        setSelectedDriver(
                          driver.driver_number
                        )
                      }
                      style={{ cursor: "pointer" }}
                    >
                      {selected && (
                        <circle
                          r="300"
                          fill="none"
                          stroke={colour}
                          strokeWidth="55"
                        />
                      )}

                      <rect
                        x="-280"
                        y="-530"
                        width="560"
                        height="240"
                        rx="55"
                        fill={colour}
                      />

                      <text
                        x="0"
                        y="-410"
                        textAnchor="middle"
                        dominantBaseline="central"
                        fill="#111"
                        fontSize="165"
                        fontWeight="bold"
                      >
                        {driver.name_acronym}
                      </text>

                      <circle
                        r="190"
                        fill={colour}
                        stroke="#fff"
                        strokeWidth="35"
                      />

                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fill="#fff"
                        fontSize="160"
                        fontWeight="bold"
                      >
                        {driver.driver_number}
                      </text>
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
        </div>

        <div className="replay-controls">
          <button
            disabled={loading || !track}
            onClick={() => {
              if (playbackTime >= endTime) {
                setPlaybackTime(startTime);
                setIsPlaying(true);
              } else {
                setIsPlaying((previous) => !previous);
              }
            }}
          >
            {isPlaying ? "⏸ Pause" : "▶ Play"}
          </button>

          <select
            className="replay-speed"
            value={speed}
            onChange={(event) =>
              setSpeed(Number(event.target.value))
            }
          >
            <option value={1}>1x</option>
            <option value={5}>5x</option>
            <option value={10}>10x</option>
            <option value={30}>30x</option>
            <option value={60}>60x</option>
            <option value={120}>120x</option>
          </select>

          <span className="replay-clock">
            {formatClock(elapsed)} /{" "}
            {formatClock(duration)}
          </span>
        </div>

        <div className="race-timeline">
          <input
            type="range"
            min={startTime}
            max={endTime}
            step={1000}
            value={playbackTime}
            disabled={loading}
            aria-label="Race replay timeline"
            onChange={(event) => {
              setPlaybackTime(
                Number(event.target.value)
              );
            }}
          />

          <div className="race-timeline-labels">
            <span>SESSION START</span>
            <span>END OF RECORDING</span>
          </div>
        </div>

        <div className="live-circuit-footer">
          <span>OPENF1 · MONTRÉAL 2026</span>
          <span>
            {visibleDrivers.length} DRIVERS ON TRACK
          </span>
        </div>
      </section>
    </main>
  );
}
