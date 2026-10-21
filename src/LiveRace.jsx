
import { useEffect, useMemo, useRef, useState } from "react";
import { buildRetirementTimes } from "./utils/retirements";
import TimingTower from "./TimingTower";
import CircuitMap from "./circuits/CircuitMap";
import "./LiveRace.css";

const DATA = "/data/montreal-2026-race";
const FALLBACK_START = Date.parse("2026-05-24T20:00:00Z");
const MAX_GAP_MS = 12000;

// Keep your preferred circuit smoothing.
const TRACK_SMOOTHING = 1.0;
const MAX_TRACK_JUMP_FACTOR = 6;

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

    if (points[mid].time < timestamp) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }

  if (points[low].time === timestamp) {
    return points[low];
  }

  if (low === 0) return null;

  const previous = points[low - 1];
  const next = points[low];
  const gap = next.time - previous.time;

  if (gap <= 0 || gap > MAX_GAP_MS) {
    return null;
  }

  const fraction = (timestamp - previous.time) / gap;

  return {
    x: previous.x + (next.x - previous.x) * fraction,
    y: previous.y + (next.y - previous.y) * fraction,
  };
}

function formatClock(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;

  return [hours, minutes, remaining]
    .map((number) => String(number).padStart(2, "0"))
    .join(":");
}

function distance(a, b) {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

function median(values) {
  if (!values.length) return 0;

  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);

  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function cleanTrackPoints(points) {
  const unique = [];

  for (const point of points) {
    if (
      !Number.isFinite(point.x) ||
      !Number.isFinite(point.y)
    ) {
      continue;
    }

    const previous = unique[unique.length - 1];

    if (!previous || distance(previous, point) > 0.01) {
      unique.push(point);
    }
  }

  if (unique.length < 4) return unique;

  const distances = [];

  for (let i = 1; i < unique.length; i++) {
    distances.push(distance(unique[i - 1], unique[i]));
  }

  const typicalDistance = median(
    distances.filter((value) => value > 0)
  );

  if (!typicalDistance) return unique;

  const maxJump = typicalDistance * MAX_TRACK_JUMP_FACTOR;
  const cleaned = [unique[0]];

  for (let i = 1; i < unique.length - 1; i++) {
    const previous = cleaned[cleaned.length - 1];
    const current = unique[i];
    const next = unique[i + 1];

    const incoming = distance(previous, current);
    const outgoing = distance(current, next);
    const bypass = distance(previous, next);

    const isolatedSpike =
      incoming > maxJump &&
      outgoing > maxJump &&
      bypass < Math.min(incoming, outgoing) * 0.6;

    if (!isolatedSpike) {
      cleaned.push(current);
    }
  }

  cleaned.push(unique[unique.length - 1]);
  return cleaned;
}

function buildSmoothPath(points, smoothing = TRACK_SMOOTHING) {
  if (!points?.length) return "";

  if (points.length === 1) {
    return `M ${points[0].x} ${points[0].y}`;
  }

  if (points.length === 2 || smoothing <= 0) {
    return points
      .map(
        (point, index) =>
          `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`
      )
      .join(" ");
  }

  const commands = [`M ${points[0].x} ${points[0].y}`];

  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];

    const segmentLength = distance(p1, p2);

    if (segmentLength < 0.001) continue;

    const factor = smoothing / 6;

    let c1x = p1.x + (p2.x - p0.x) * factor;
    let c1y = p1.y + (p2.y - p0.y) * factor;
    let c2x = p2.x - (p3.x - p1.x) * factor;
    let c2y = p2.y - (p3.y - p1.y) * factor;

    const maxHandle = segmentLength * 0.45;

    const handle1 = Math.hypot(c1x - p1.x, c1y - p1.y);

    if (handle1 > maxHandle) {
      const scale = maxHandle / handle1;
      c1x = p1.x + (c1x - p1.x) * scale;
      c1y = p1.y + (c1y - p1.y) * scale;
    }

    const handle2 = Math.hypot(c2x - p2.x, c2y - p2.y);

    if (handle2 > maxHandle) {
      const scale = maxHandle / handle2;
      c2x = p2.x + (c2x - p2.x) * scale;
      c2y = p2.y + (c2y - p2.y) * scale;
    }

    commands.push(
      `C ${c1x} ${c1y} ${c2x} ${c2y} ${p2.x} ${p2.y}`
    );
  }

  return commands.join(" ");
}

function buildTrack(locations, laps) {
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
    const end = start + Number(lap.lap_duration) * 1000;

    const segment = points.filter(
      (point) =>
        point.time >= start &&
        point.time <= end
    );

    if (segment.length >= 45) {
      circuitPoints = segment;
      break;
    }
  }

  if (circuitPoints.length < 20) return null;

  const cleanedPoints = cleanTrackPoints(circuitPoints);

  if (cleanedPoints.length < 20) return null;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const point of cleanedPoints) {
    minX = Math.min(minX, point.x);
    maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y);
    maxY = Math.max(maxY, point.y);
  }

  const padding = 150;

  const svgPoints = cleanedPoints.map((point) => ({
    x: point.x - minX + padding,
    y: maxY - point.y + padding,
  }));

  const path = buildSmoothPath(svgPoints);

  return {
    path,
    minX,
    maxX,
    minY,
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
  const [retirements, setRetirements] = useState({});
  const [dnsDrivers, setDnsDrivers] = useState([]);

  const [startTime, setStartTime] = useState(FALLBACK_START);
  const [endTime, setEndTime] = useState(
    FALLBACK_START + 2 * 60 * 60 * 1000
  );
  const [playbackTime, setPlaybackTime] = useState(FALLBACK_START);

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
          "race_control.json",
          "session_result.json",
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
            throw new Error(`Could not load ${files[index]}`);
          }
        }

        const [
          sessionData,
          driverData,
          locationData,
          lapData,
          raceControlData,
          sessionResults,
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

        const sessionStart = Date.parse(session?.date_start);

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

        const detectedRetirements = buildRetirementTimes({
          raceControl: raceControlData,
          sessionResults,
          laps: lapData,
          locations: grouped,
        });
        const detectedDNS = sessionResults
          .filter((result) => result.dns === true)
          .map((result) => Number(result.driver_number));

        console.log("DNS drivers:", detectedDNS);

        console.table(
          Object.entries(detectedRetirements).map(
            ([number, time]) => ({
              driver: number,
              retirementTime: new Date(time).toISOString(),
            })
          )
        );

        if (!controller.signal.aborted) {
          setDrivers(uniqueDrivers);
          setLocations(grouped);
          setLaps(lapData);
          setRetirements(detectedRetirements);
          setDnsDrivers(detectedDNS);
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
        Math.min(endTime, previous + elapsed * speed)
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
        const number = Number(driver.driver_number);
        const retirementTime = retirements[number];

        // A DNS driver never appears in the race replay.
        if (dnsDrivers.includes(number)) {
          return null;
        }

        // A retired driver disappears at their retirement time.
        if (
          retirementTime !== undefined &&
          playbackTime >= retirementTime
        ) {
          return null;
        }

        const position = findPosition(
          locations[number],
          playbackTime
        );

        return position
          ? { ...driver, position }
          : null;
      })
      .filter(Boolean),
  [drivers, locations, retirements, dnsDrivers, playbackTime]
);

  
const driverStatuses = useMemo(() => {
  const statuses = {};

  for (const number of dnsDrivers) {
    statuses[number] = "DNS";
  }

  for (const [number, time] of Object.entries(retirements)) {
    if (playbackTime >= time) {
      statuses[number] = "OUT";
    }
  }

  return statuses;
}, [dnsDrivers, retirements, playbackTime]);


  const elapsed = playbackTime - startTime;
  const duration = endTime - startTime;

  return (
    <main className="live-race-page">
      {/* HEADER */}
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
        {/* CIRCUIT HEADING */}
        <div className="live-circuit-heading">
          <h3>CIRCUIT GILLES-VILLENEUVE</h3>
          <span>RACE TRACKER</span>
        </div>

        {/* TIMING TOWER + CIRCUIT */}
        <div className="live-race-content">
          <TimingTower
            drivers={drivers}
            playbackTime={playbackTime}
            selectedDriver={selectedDriver}
            onSelectDriver={setSelectedDriver}
            driverStatuses={driverStatuses}
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

            {/* SMOOTH CIRCUIT MAP */}
            {!loading && !error && track && (
              <CircuitMap
                track={track}
                drivers={visibleDrivers}
                selectedDriver={selectedDriver}
                onSelectDriver={setSelectedDriver}
              />
            )}
          </div>
        </div>

        {/* PLAYBACK CONTROLS */}
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

        {/* RACE TIMELINE */}
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
              setPlaybackTime(Number(event.target.value));
            }}
          />

          <div className="race-timeline-labels">
            <span>SESSION START</span>
            <span>END OF RECORDING</span>
          </div>
        </div>

        {/* FOOTER */}
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
