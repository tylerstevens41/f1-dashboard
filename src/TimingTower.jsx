
import { useEffect, useMemo, useState } from "react";
import "./TimingTower.css";

const DATA = "/data/montreal-2026-race";
const TOTAL_LAPS = 68;

// ========================================
// TEAM LOGOS
// ========================================

function getTeamLogo(teamName) {
  const team = String(teamName || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");

  if (
    team.includes("racingbulls") ||
    team.includes("visacashapprb")
  ) {
    return "/teams/racing-bulls.png";
  }

  if (team.includes("redbull")) {
    return "/teams/redbull.png";
  }

  if (team.includes("ferrari")) {
    return "/teams/ferrari.png";
  }

  if (team.includes("mercedes")) {
    return "/teams/mercedes.png";
  }

  if (team.includes("mclaren")) {
    return "/teams/mclaren.png";
  }

  if (team.includes("astonmartin")) {
    return "/teams/aston-martin.png";
  }

  if (team.includes("alpine")) {
    return "/teams/alpine.png";
  }

  if (team.includes("williams")) {
    return "/teams/williams.png";
  }

  if (team.includes("haas")) {
    return "/teams/haas.png";
  }

  if (team.includes("audi")) {
    return "/teams/audi.png";
  }

  if (team.includes("cadillac")) {
    return "/teams/cadillac.png";
  }

  return null;
}

// ========================================
// FORMATTING
// ========================================

function formatLap(value) {
  if (value == null || value === "") return "—";

  const seconds = Number(value);

  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "—";
  }

  const minutes = Math.floor(seconds / 60);

  const remainder = (seconds % 60)
    .toFixed(3)
    .padStart(6, "0");

  return `${minutes}:${remainder}`;
}

function formatGap(value) {
  if (value == null || value === "") return "—";

  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return String(value);
  }

  if (numeric === 0) return "—";

  return `+${numeric.toFixed(1)}`;
}

// ========================================
// DATA HELPERS
// ========================================

function latestBefore(records, timestamp) {
  if (!records?.length) return null;

  let low = 0;
  let high = records.length;

  while (low < high) {
    const mid = Math.floor((low + high) / 2);

    if (records[mid].time <= timestamp) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }

  return records[low - 1] || null;
}

function groupByDriver(records, getTime) {
  const grouped = {};

  for (const record of records) {
    const time = getTime(record);
    const number = Number(record.driver_number);

    if (
      !Number.isFinite(time) ||
      !Number.isFinite(number)
    ) {
      continue;
    }

    if (!grouped[number]) {
      grouped[number] = [];
    }

    grouped[number].push({
      ...record,
      time,
    });
  }

  for (const records of Object.values(grouped)) {
    records.sort((a, b) => a.time - b.time);
  }

  return grouped;
}

function completedLapCount(records, timestamp) {
  if (!records?.length) return 0;

  let low = 0;
  let high = records.length;

  while (low < high) {
    const mid = Math.floor((low + high) / 2);

    if (records[mid].time <= timestamp) {
      low = mid + 1;
    } else {
      high = mid;
    }
  }

  return low;
}

// ========================================
// SVG TYRE ICONS
// ========================================

function TyreIcon({ compound }) {
  const tyre = String(compound || "").toLowerCase();

  const validTyres = [
    "soft",
    "medium",
    "hard",
    "intermediate",
    "wet",
  ];

  if (!validTyres.includes(tyre)) {
    return <span className="f1-no-tyre">—</span>;
  }

  return (
    <img
      src={`/tyres/${tyre}.svg`}
      alt={`${tyre} tyre`}
      title={`${tyre.toUpperCase()} tyre`}
      className="f1-tyre-image"
    />
  );
}

// ========================================
// RETIREMENT DETECTION
// ========================================

function getRetirements(raceControl) {
  const retirements = {};

  for (const event of raceControl) {
    const message = String(
      event.message || ""
    ).toUpperCase();

    const number = Number(event.driver_number);
    const time = Date.parse(event.date);

    if (
      !Number.isFinite(number) ||
      number <= 0 ||
      !Number.isFinite(time)
    ) {
      continue;
    }

    const isRetirement =
      /\bRETIRED\b/.test(message) ||
      /\bRETIREMENT\b/.test(message) ||
      /\bWILL NOT RESTART\b/.test(message);

    if (!isRetirement) continue;

    if (
      retirements[number] === undefined ||
      time < retirements[number]
    ) {
      retirements[number] = time;
    }
  }

  return retirements;
}

// ========================================
// PIT STOP DETECTION
// ========================================

function getPitWindows(pitStops) {
  const pitWindows = {};

  for (const stop of pitStops) {
    const number = Number(stop.driver_number);
    const timestamp = Date.parse(stop.date);

    if (
      !Number.isFinite(number) ||
      number <= 0 ||
      !Number.isFinite(timestamp)
    ) {
      continue;
    }

    const duration = Number(stop.pit_duration);

    const durationMs =
      Number.isFinite(duration) && duration > 0
        ? duration * 1000
        : 25000;

    // Approximate the pit-lane window.
    const start = timestamp - durationMs;
    const end = timestamp + 5000;

    if (!pitWindows[number]) {
      pitWindows[number] = [];
    }

    pitWindows[number].push({
      start,
      end,
    });
  }

  for (const windows of Object.values(pitWindows)) {
    windows.sort((a, b) => a.start - b.start);
  }

  return pitWindows;
}

// ========================================
// GROUP PIT STOPS BY DRIVER
// ========================================

function groupPitStops(pitStops) {
  const grouped = {};

  for (const stop of pitStops) {
    const number = Number(stop.driver_number);
    const timestamp = Date.parse(stop.date);

    if (
      !Number.isFinite(number) ||
      number <= 0 ||
      !Number.isFinite(timestamp)
    ) {
      continue;
    }

    if (!grouped[number]) {
      grouped[number] = [];
    }

    grouped[number].push({
      ...stop,
      time: timestamp,
    });
  }

  for (const stops of Object.values(grouped)) {
    stops.sort((a, b) => a.time - b.time);
  }

  return grouped;
}

// ========================================
// TYRE CHANGE SYNCHRONIZATION
// ========================================

function getTyreCompoundAtTime(
  stints,
  pitStops,
  playbackTime
) {
  if (!stints?.length) return null;

  const sortedStints = [...stints].sort(
    (a, b) =>
      Number(a.lap_start) - Number(b.lap_start)
  );

  const sortedPits = [...(pitStops || [])].sort(
    (a, b) => a.time - b.time
  );

  // Starting tyre compound.
  let compound = sortedStints[0].compound;

  // Activate the next stint only after
  // reaching the corresponding pit event.
  for (
    let index = 0;
    index < sortedPits.length;
    index++
  ) {
    if (playbackTime < sortedPits[index].time) {
      break;
    }

    const nextStint = sortedStints[index + 1];

    if (nextStint) {
      compound = nextStint.compound;
    }
  }

  return compound;
}

// ========================================
// TIMING TOWER
// ========================================

export default function TimingTower({
  drivers = [],
  playbackTime,
  selectedDriver,
  onSelectDriver,
  driverStatuses = {},
}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  // ======================================
  // LOAD RACE DATA
  // ======================================

  useEffect(() => {
    const controller = new AbortController();

    async function loadTiming() {
      try {
        const files = [
          "positions.json",
          "laps.json",
          "intervals.json",
          "stints.json",
          "race_control.json",
          "pit.json",
        ];

        const responses = await Promise.all(
          files.map((filename) =>
            fetch(`${DATA}/${filename}`, {
              signal: controller.signal,
            })
          )
        );

        for (
          let index = 0;
          index < responses.length;
          index++
        ) {
          if (!responses[index].ok) {
            throw new Error(
              `Could not load ${files[index]}`
            );
          }
        }

        const [
          positions,
          laps,
          intervals,
          stints,
          raceControl,
          pitStops,
        ] = await Promise.all(
          responses.map((response) => response.json())
        );

        // Group positions.
        const groupedPositions = groupByDriver(
          positions,
          (record) => Date.parse(record.date)
        );

        // Group intervals.
        const groupedIntervals = groupByDriver(
          intervals,
          (record) => Date.parse(record.date)
        );

        // Group completed laps.
        const groupedLaps = groupByDriver(
          laps.filter(
            (lap) =>
              lap.date_start &&
              Number(lap.lap_duration) > 0
          ),
          (lap) =>
            Date.parse(lap.date_start) +
            Number(lap.lap_duration) * 1000
        );

        // Group tyre stints.
        const groupedStints = {};

        for (const stint of stints) {
          const number = Number(stint.driver_number);

          if (!groupedStints[number]) {
            groupedStints[number] = [];
          }

          groupedStints[number].push(stint);
        }

        for (const records of Object.values(
          groupedStints
        )) {
          records.sort(
            (a, b) =>
              Number(a.lap_start) -
              Number(b.lap_start)
          );
        }

        // Detect retirements.
        const retirements = getRetirements(
          raceControl
        );

        // Detect pit windows.
        const pitWindows = getPitWindows(
          pitStops
        );

        // Store pit events for tyre changes.
        const groupedPitStops = groupPitStops(
          pitStops
        );

        console.log(
          "Detected race-control retirements:",
          retirements
        );

        console.log(
          "Detected pit windows:",
          pitWindows
        );

        if (!controller.signal.aborted) {
          setData({
            positions: groupedPositions,
            intervals: groupedIntervals,
            laps: groupedLaps,
            stints: groupedStints,
            retirements,
            pitWindows,
            pitStops: groupedPitStops,
          });
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          setError(err.message);
        }
      }
    }

    loadTiming();

    return () => controller.abort();
  }, []);

  // ======================================
  // BUILD TIMING ROWS
  // ======================================

  const rows = useMemo(() => {
    if (!data) return [];

    return drivers
      .map((driver) => {
        const number = Number(
          driver.driver_number
        );

        const positionRecord = latestBefore(
          data.positions[number],
          playbackTime
        );

        const intervalRecord = latestBefore(
          data.intervals[number],
          playbackTime
        );

        const lapRecords =
          data.laps[number] || [];

        const completedCount =
          completedLapCount(
            lapRecords,
            playbackTime
          );

        const completedLaps =
          lapRecords.slice(0, completedCount);

        const lastLap = completedLaps.at(-1);

        // Best lap so far.
        let bestLap = null;

        for (const lap of completedLaps) {
          const duration = Number(
            lap.lap_duration
          );

          if (
            Number.isFinite(duration) &&
            duration > 0 &&
            (
              bestLap === null ||
              duration < bestLap
            )
          ) {
            bestLap = duration;
          }
        }

        const completedLapNumber =
          Number(lastLap?.lap_number) || 0;

        // ==================================
        // SYNCHRONIZED TYRE COMPOUND
        // ==================================

        const tyreCompound = getTyreCompoundAtTime(
          data.stints[number],
          data.pitStops[number],
          playbackTime
        );

        // ==================================
        // OUT STATUS
        // ==================================

        const retirementTime =
          data.retirements[number];

        const isOut =
          Boolean(driverStatuses[number]) ||
          (
            retirementTime !== undefined &&
            playbackTime >= retirementTime
          );

        // ==================================
        // PIT STATUS
        // ==================================

        const isPitting = (
          data.pitWindows[number] || []
        ).some(
          (window) =>
            playbackTime >= window.start &&
            playbackTime <= window.end
        );

        return {
          ...driver,
          position:
            positionRecord?.position ?? null,
          gap:
            intervalRecord?.interval ?? null,
          leaderGap:
            intervalRecord?.gap_to_leader ??
            null,
          bestLap,
          lastLap:
            lastLap?.lap_duration ?? null,
          completedLapNumber,
          tyre: tyreCompound,
          isOut,
          isPitting,
        };
      })
      .sort((a, b) => {
        if (
          a.position == null &&
          b.position == null
        ) {
          return (
            Number(a.driver_number) -
            Number(b.driver_number)
          );
        }

        if (a.position == null) return 1;
        if (b.position == null) return -1;

        return (
          Number(a.position) -
          Number(b.position)
        );
      });
  }, [
    drivers,
    data,
    playbackTime,
    driverStatuses,
  ]);

  const leader = rows.find(
    (driver) =>
      Number(driver.position) === 1
  );

  const leaderLap =
    leader?.completedLapNumber ?? 0;

  // ======================================
  // RENDER
  // ======================================

  return (
    <aside className="timing-tower f1-timing-tower">
      <div className="timing-tower-title">
        <h3>RACE TIMING</h3>

        <span>
          {leaderLap > 0
            ? `LAP ${Math.min(
                leaderLap + 1,
                TOTAL_LAPS
              )}/${TOTAL_LAPS}`
            : "RACE START"}
        </span>
      </div>

      <div className="f1-timing-head">
        <span>POS</span>
        <span>DRIVER</span>
        <span>GAP</span>
        <span>TYRE</span>
        <span>BEST LAP</span>
        <span>LEADER</span>
        <span>LAST LAP</span>
      </div>

      <div className="f1-timing-body">
        {!data && !error && (
          <p className="timing-message">
            Loading race timing...
          </p>
        )}

        {error && (
          <p className="timing-message">
            {error}
          </p>
        )}

        {rows.map((driver) => {
          const logo = getTeamLogo(
            driver.team_name
          );

          const selected =
            Number(selectedDriver) ===
            Number(driver.driver_number);

          return (
            <button
              key={driver.driver_number}
              className={`f1-timing-row ${
                selected ? "selected" : ""
              } ${
                driver.isOut
                  ? "driver-out"
                  : ""
              }`}
              onClick={() =>
                onSelectDriver?.(
                  driver.driver_number
                )
              }
            >
              {/* POSITION */}

              <span
                className={`f1-position-badge ${
                  Number(driver.position) === 1
                    ? "leader"
                    : ""
                }`}
              >
                {driver.position ?? "—"}
              </span>

              {/* DRIVER + TEAM LOGO */}

              <span className="f1-driver-cell">
                <span
                  className="f1-team-colour"
                  style={{
                    background: `#${
                      driver.team_colour ||
                      "FFFFFF"
                    }`,
                  }}
                />

                {logo && (
                  <img
                    className="f1-team-logo"
                    src={logo}
                    alt=""
                  />
                )}

                <strong>
                  {driver.name_acronym}
                </strong>
              </span>

              {/* GAP / PIT / OUT */}

              <span
                className={`f1-number ${
                  driver.isOut
                    ? "f1-out-label"
                    : driver.isPitting
                      ? "f1-pit-label"
                      : ""
                }`}
              >
                {driver.isOut
                  ? "OUT"
                  : driver.isPitting
                    ? "PIT"
                    : Number(driver.position) === 1
                      ? "—"
                      : formatGap(driver.gap)}
              </span>

              {/* TYRE */}

              <span className="f1-tyre-cell">
                <TyreIcon
                  compound={driver.tyre}
                />
              </span>

              {/* BEST LAP */}

              <span className="f1-number">
                {formatLap(
                  driver.bestLap
                )}
              </span>

              {/* GAP TO LEADER */}

              <span className="f1-number">
                {Number(
                  driver.position
                ) === 1
                  ? "LEADER"
                  : formatGap(
                      driver.leaderGap
                    )}
              </span>

              {/* LAST LAP */}

              <span className="f1-number">
                {formatLap(
                  driver.lastLap
                )}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
