import useRaceFeed from "./race/useRaceFeed";
import RaceDevTools from "./race/RaceDevTools";
import { flattenRecord, selectCircuit, tyrePresentation } from "./race/state";

import {
  useMemo,
  useState,
} from "react";

import LiveCircuitSvg from "./circuits/LiveCircuitSvg";

import "./LiveRace.css";
import "./TimingTower.css";

// ============================================
// CONFIGURATION
// ============================================


const EMPTY = Object.freeze({});
function playbackClock(ms) {
  return Number.isFinite(ms) ? `${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}` : '—';
}

const TEAM_LOGOS = {
  mercedes: "mercedes",
  ferrari: "ferrari",
  "red bull racing": "redbull",
  "red bull": "redbull",
  mclaren: "mclaren",
  "aston martin": "aston-martin",
  alpine: "alpine",
  "haas f1 team": "haas",
  haas: "haas",
  williams: "williams",
  "racing bulls": "racing-bulls",
  "rb f1 team": "racing-bulls",
  "visa cash app rb": "racing-bulls",
  "kick sauber": "audi",
  audi: "audi",
  cadillac: "cadillac",
};

// ============================================
// DATA HELPERS
// ============================================

function readField(record, path) {
  if (!record) {
    return undefined;
  }

  if (record[path] !== undefined) {
    return record[path];
  }

  const flattened = path.replace(/\./g, "_");

  if (record[flattened] !== undefined) {
    return record[flattened];
  }

  return path.split(".").reduce(
    (value, key) => value?.[key],
    record
  );
}

function firstField(record, paths) {
  for (const path of paths) {
    const value = readField(record, path);

    if (
      value !== undefined &&
      value !== null &&
      value !== ""
    ) {
      return value;
    }
  }

  return null;
}

function formatLap(value) {
  if (value == null || value === "") {
    return "—";
  }

  if (typeof value === "object") {
    value = value.Value ?? value.value;
  }

  if (value == null || value === "") {
    return "—";
  }

  if (typeof value === "number") {
    const minutes = Math.floor(value / 60);
    const seconds = (value % 60).toFixed(3);

    return `${minutes}:${seconds.padStart(6, "0")}`;
  }

  return String(value);
}

function formatGap(value) {
  if (value == null || value === "") {
    return "—";
  }

  if (typeof value === "object") {
    value = value.Value ?? value.value;
  }

  if (value == null || value === "") {
    return "—";
  }

  return String(value);
}

function getTeamLogo(teamName) {
  const key = String(teamName ?? "")
    .trim()
    .toLowerCase();

  const filename = TEAM_LOGOS[key];

  return filename
    ? `/teams/${filename}.png`
    : null;
}

// ============================================
// TYRE HELPERS
// ============================================

function getCompound(data) {
  const direct = firstField(data, [
    "Compound",
    "TyreCompound",
    "CurrentStint.Compound",
    "CurrentStint_Compound",
  ]);

  if (direct) {
    return String(direct).toUpperCase();
  }

  const stintKeys = Object.keys(data ?? {})
    .filter((key) =>
      /^Stints_\d+_Compound$/.test(key)
    )
    .sort((a, b) => {
      const aIndex = Number(
        a.match(/\d+/)?.[0] ?? 0
      );

      const bIndex = Number(
        b.match(/\d+/)?.[0] ?? 0
      );

      return bIndex - aIndex;
    });

  for (const key of stintKeys) {
    if (data[key]) {
      return String(data[key]).toUpperCase();
    }
  }

  if (Array.isArray(data?.Stints)) {
    const latest = data.Stints.at(-1);

    return String(
      latest?.Compound ?? ""
    ).toUpperCase();
  }

  return "";
}

function getTyreAge(data) {
  return firstField(data, [
    "TyresAge",
    "TyreAge",
    "CurrentStint.TotalLaps",
    "CurrentStint_TotalLaps",
    "TotalLaps",
  ]);
}

function getTyreCode(compound) {
  const codes = {
    SOFT: "S",
    MEDIUM: "M",
    HARD: "H",
    INTERMEDIATE: "I",
    WET: "W",
  };

  return codes[compound] ?? "";
}

function TyreDisplay({ data }) {
  const compound = getCompound(data);
  const code = getTyreCode(compound);
  const age = getTyreAge(data);

  if (!code) {
    return (
      <span style={{ color: "#7d8492" }}>
        —
      </span>
    );
  }

  const colors = {
    S: "#e10600",
    M: "#ffd400",
    H: "#f4f4f4",
    I: "#27b86b",
    W: "#3295f0",
  };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
      }}
      title={`${compound}${
        age != null ? ` · ${age} laps` : ""
      }`}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          border: `3px solid ${colors[code]}`,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 9,
          fontWeight: 800,
          color: "#fff",
          boxSizing: "border-box",
        }}
      >
        {code}
      </span>

      {age != null && (
        <span
          style={{
            fontSize: 10,
            color: "#c6cad3",
          }}
        >
          {age}L
        </span>
      )}
    </span>
  );
}

// ============================================
// DRIVER STATUS
// ============================================

function getStatus(timing) {
  const status = String(
    firstField(timing, [
      "Status",
      "DriverStatus",
    ]) ?? ""
  ).toLowerCase();

  if (
    timing?.Retired === true ||
    timing?.Stopped === true ||
    ["out", "retired", "stopped"].includes(status)
  ) {
    return "OUT";
  }

  if (
    timing?.InPit === true ||
    timing?.PitIn === true ||
    ["pit", "inpit"].includes(status)
  ) {
    return "PIT";
  }

  return "";
}

// ============================================
// SESSION HELPERS
// ============================================

function getSessionName(session) {
  return (
    firstField(session, [
      "Meeting.Name",
      "Meeting_Name",
      "Meeting.OfficialName",
      "Meeting_OfficialName",
      "Name",
    ]) ?? "Live Formula 1 Session"
  );
}

function getSessionType(session) {
  return (
    firstField(session, [
      "Type",
      "SessionType",
      "Session.Type",
      "Session_Type",
    ]) ?? "Live"
  );
}

// ============================================
// MAIN COMPONENT
// ============================================

export default function LiveSession() {
  const feed = useRaceFeed();
  const { race, connection } = feed;
  const session = race.topics.SessionInfo ?? EMPTY;
  const driversByNumber = race.topics.DriverList ?? EMPTY;
  const timingByNumber = race.topics.TimingData ?? EMPTY;
  const tyresByNumber = race.topics.TimingAppData ?? EMPTY;
  const positionsByNumber = race.topics["Position.z"] ?? EMPTY;
  const [selectedDriver, setSelectedDriver] =
    useState(null);

  // ==========================================
  // BUILD DRIVER DATA
  // ==========================================

  const drivers = useMemo(() => {
    return Object.entries(driversByNumber)
      .map(([number, driver]) => {
        const timing =
          flattenRecord(timingByNumber[number] ?? {});

        const tyre =
          tyrePresentation(tyresByNumber[number] ?? {});

        const rawPosition =
          firstField(timing, ["Position", "Line"]) ??
          firstField(driver, ["Position", "Line"]);

        const position = Number(rawPosition);

        return {
          driver_number: number,

          name_acronym:
            driver.Tla ??
            driver.name_acronym ??
            driver.BroadcastName ??
            number,

          full_name:
            driver.FullName ??
            driver.full_name ??
            "",

          team_name:
            driver.TeamName ??
            driver.team_name ??
            "",

          team_colour: String(
            driver.TeamColour ??
            driver.team_colour ??
            "FFFFFF"
          ).replace("#", ""),

          position:
            Number.isFinite(position) &&
            position > 0
              ? position
              : 999,

          timing,
          tyre,

          gps:
            positionsByNumber[number] ?? {},
        };
      })
      .sort(
        (a, b) =>
          a.position - b.position ||
          Number(a.driver_number) -
            Number(b.driver_number)
      );
  }, [
    driversByNumber,
    timingByNumber,
    tyresByNumber,
    positionsByNumber,
  ]);

  const gpsDrivers = useMemo(() => drivers.filter(driver => driver.gps && Number.isFinite(driver.gps.X) && Number.isFinite(driver.gps.Y)), [drivers]);

  // ==========================================
  // CIRCUIT
  // ==========================================

  const sessionName = getSessionName(session);
  const sessionType = getSessionType(session);

  // Never silently display Austin for another event.
  const circuitName = selectCircuit(session);

  const towerHeaderHeight = 36;
  const columnHeaderHeight = 26;
  const rowHeight = `clamp(18px, calc((100dvh - 270px) / ${Math.max(22,drivers.length)}), 30px)`;

  // ==========================================
  // RENDER
  // ==========================================

  return (
    <main
      className="live-race-page live-session-page"
      style={{
        color: "#ffffff",
        minHeight: 0,
      }}
    >
      {import.meta.env.DEV && <RaceDevTools feed={feed} circuit={circuitName} />}
      <div style={{ padding: "0 16px", color: race.mode === "TEST" ? "#ffd43b" : "#40d98a" }}>{race.mode === "TEST" ? "TEST · historical LiveF1 data" : "LIVE"} · {race.upstream}{race.mode === 'TEST' && ` · ${race.playback} · ${playbackClock(race.playbackInfo?.offsetMs)} / ${playbackClock(race.playbackInfo?.durationMs)}`}</div>
      {/* SESSION HEADER */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          padding: "12px 16px",
        }}
      >
        <div>
          <h2
            style={{
              margin: 0,
              fontSize: 20,
            }}
          >
            {sessionName}
          </h2>

          <div
            style={{
              marginTop: 4,
              color: "#aab1bf",
              fontSize: 11,
            }}
          >
            {sessionType}
          </div>
        </div>

        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color:
              connection === "connected"
                ? "#40d98a"
                : "#ffbf47",
          }}
        >
          ● {connection.toUpperCase()}
        </span>
      </div>

      {/* MAIN DASHBOARD GRID */}
      <div
        className="live-session-layout"
        style={{
          display: "grid",
          gridTemplateColumns:
            "minmax(440px, 43%) minmax(0, 1fr)",
          gap: 12,
          padding: "0 16px 12px",
          alignItems: "stretch",
        }}
      >
        {/* TIMING TOWER */}
        <aside
          className="timing-tower f1-timing-tower live-session-tower"
          style={{
            background: "#0c0e13",
            borderRadius: 10,
            overflow: "hidden",
            minWidth: 0,
            height: "100%",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              height: towerHeaderHeight,
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              padding: "0 12px",
              fontWeight: 700,
              fontSize: 13,
              borderBottom:
                "1px solid #292d35",
            }}
          >
            LIVE TIMING
          </div>

          <div
            style={{
              flex: 1,
              minHeight: 0,
              overflowX: "auto",
              overflowY: "auto",
            }}
          >
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                color: "#ffffff",
                fontSize: 11,
                whiteSpace: "nowrap",
                tableLayout: "auto",
              }}
            >
              <thead>
                <tr
                  style={{
                    height: columnHeaderHeight,
                    color: "#939ba9",
                    fontSize: 9,
                    textAlign: "left",
                  }}
                >
                  {[
                    "POS",
                    "DRIVER",
                    "GAP",
                    "TYRE",
                    "BEST LAP",
                    "LAST LAP",
                  ].map((heading) => (
                    <th
                      key={heading}
                      style={{
                        padding: "0 6px",
                        height: columnHeaderHeight,
                        borderBottom:
                          "1px solid #292d35",
                        fontWeight: 700,
                      }}
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody>
                {drivers.map((driver) => {
                  const { timing, tyre } = driver;

                  const status = getStatus(timing);

                  const logo = getTeamLogo(
                    driver.team_name
                  );

                  const isSelected =
                    selectedDriver ===
                    driver.driver_number;

                  const gap = firstField(timing, [
                    "GapToLeader",
                    "GapToLeader.Value",
                  ]);

                  const bestLap = firstField(
                    timing,
                    [
                      "BestLapTime.Value",
                      "BestLapTime_Value",
                      "BestLapTime",
                    ]
                  );

                  const lastLap = firstField(
                    timing,
                    [
                      "LastLapTime.Value",
                      "LastLapTime_Value",
                      "LastLapTime",
                    ]
                  );

                  return (
                    <tr
                      key={driver.driver_number}
                      onClick={() =>
                        setSelectedDriver(
                          driver.driver_number
                        )
                      }
                      style={{
                        height: rowHeight,
                        cursor: "pointer",
                        background: isSelected
                          ? "#252b36"
                          : "transparent",
                        borderBottom:
                          "1px solid #222630",
                      }}
                    >
                      {/* POSITION */}
                      <td
                        style={{
                          padding: "0 6px",
                          height: rowHeight,
                        }}
                      >
                        {driver.position === 999
                          ? "—"
                          : driver.position}
                      </td>

                      {/* DRIVER + TEAM LOGO */}
                      <td
                        style={{
                          padding: "0 6px",
                          height: rowHeight,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 5,
                            borderLeft:
                              `3px solid #${driver.team_colour}`,
                            paddingLeft: 5,
                          }}
                        >
                          {logo && (
                            <img
                              src={logo}
                              alt=""
                              style={{
                                width: 15,
                                height: 15,
                                objectFit:
                                  "contain",
                                flexShrink: 0,
                              }}
                              onError={(event) => {
                                event.currentTarget.style.display =
                                  "none";
                              }}
                            />
                          )}

                          <strong
                            style={{
                              fontSize: 11,
                            }}
                          >
                            {driver.name_acronym}
                          </strong>
                        </div>
                      </td>

                      {/* GAP / PIT / OUT */}
                      <td
                        style={{
                          padding: "0 6px",
                          height: rowHeight,
                        }}
                      >
                        {status ? (
                          <strong
                            style={{
                              color:
                                status === "OUT"
                                  ? "#ff5656"
                                  : "#ffca54",
                            }}
                          >
                            {status}
                          </strong>
                        ) : (
                          formatGap(gap)
                        )}
                      </td>

                      {/* TYRE */}
                      <td
                        style={{
                          padding: "0 6px",
                          height: rowHeight,
                        }}
                      >
                        <TyreDisplay data={tyre} />
                      </td>

                      {/* BEST LAP */}
                      <td
                        style={{
                          padding: "0 6px",
                          height: rowHeight,
                        }}
                      >
                        {formatLap(bestLap)}
                      </td>

                      {/* LAST LAP */}
                      <td
                        style={{
                          padding: "0 6px",
                          height: rowHeight,
                        }}
                      >
                        {formatLap(lastLap)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {drivers.length === 0 && (
              <div
                style={{
                  padding: 18,
                  color: "#aab1bf",
                  fontSize: 12,
                }}
              >
                Waiting for live driver information...
              </div>
            )}
          </div>
        </aside>

        {/* LIVE CIRCUIT */}
        <section
          className="live-circuit-area"
          style={{
            minWidth: 0,
            minHeight: 0,
          }}
        >
          {circuitName ? <LiveCircuitSvg
            key={`${race.generation}-${circuitName}`}
            animation={feed.animation}
            mode={race.mode}
            circuitName={circuitName}
            drivers={gpsDrivers}
            selectedDriver={selectedDriver}
            onSelectDriver={setSelectedDriver}
          /> : <p>No verified circuit mapping for this session. Timing remains available.</p>}
        </section>
      </div>

      {/* FOOTER */}
      <div
        className="live-session-footer"
        style={{
          padding: "0 16px 6px",
          color: "#939ba9",
          fontSize: 10,
        }}
      >
        {drivers.length} drivers loaded ·{" "}
        {gpsDrivers.length} drivers with GPS data

        {race.clockMs && ` · ${race.mode} · ${race.clockBasis === "relative" ? `${(race.clockMs / 1000).toFixed(1)}s (relative archive clock)` : new Date(race.clockMs).toLocaleTimeString()}`}
        <p>{race.topics.TrackStatus?.Message ?? "Track status unavailable"} · {race.topics.SessionStatus?.Status ?? "Session status unavailable"}</p>
        {Object.values(race.topics.RaceControlMessages?.Messages ?? {}).slice(-3).map((message, index) => <p key={index}>{message.Message}</p>)}
      </div>
    </main>
  );
}
