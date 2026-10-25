
import LiveRace from "./LiveRace";
import { useEffect, useState } from "react";
import "./App.css";

const API_BASE = "https://api.jolpi.ca/ergast/f1";

// Manually maintained team colours
const TEAM_COLORS = {
  mclaren: "#FF8000",
  red_bull: "#3671C6",
  ferrari: "#E8002D",
  mercedes: "#27F4D2",
  aston_martin: "#00665E",
  alpine: "#0090FF",
  haas: "#E6002B",
  rb: "#FFFFFF",
  rb_f1_team: "#FFFFFF",
  racing_bulls: "#FFFFFF",
  williams: "#64C4FF",
  sauber: "#52E252",
  audi: "#F50537",
  cadillac: "#FFFFFF",
};

const TEAM_NAMES = {
  mclaren: "McLaren",
  mercedes: "Mercedes",
  red_bull: "Red Bull Racing",
  ferrari: "Ferrari",
  williams: "Williams",
  rb: "Racing Bulls",
  rb_f1_team: "Racing Bulls",
  racing_bulls: "Racing Bulls",
  aston_martin: "Aston Martin",
  haas: "Haas",
  alpine: "Alpine",
  audi: "Audi",
  cadillac: "Cadillac",
};

// Team logos stored in public/teams/
const TEAM_LOGOS = {
  mclaren: "/teams/mclaren.png",
  red_bull: "/teams/redbull.png",
  ferrari: "/teams/ferrari.png",
  mercedes: "/teams/mercedes.png",
  aston_martin: "/teams/aston-martin.png",
  alpine: "/teams/alpine.png",
  haas: "/teams/haas.png",
  rb: "/teams/racing-bulls.png",
  rb_f1_team: "/teams/racing-bulls.png",
  racing_bulls: "/teams/racing-bulls.png",
  williams: "/teams/williams.png",
  sauber: "/teams/sauber.png",
  audi: "/teams/audi.png",
  cadillac: "/teams/cadillac.png",
};

function getTeamName(constructor) {
  if (!constructor) return "Unknown Team";

  const id = constructor.constructorId?.toLowerCase() || "";
  const name = constructor.name?.toLowerCase() || "";

  if (
    id === "rb" ||
    id === "racing_bulls" ||
    id === "rb_f1_team" ||
    name === "rb f1 team" ||
    name.includes("racing bulls")
  ) {
    return "Racing Bulls";
  }

  return TEAM_NAMES[id] || constructor.name || "Unknown Team";
}

function getTeamColor(id) {
  return TEAM_COLORS[id?.toLowerCase()] || "#777777";
}

function TeamLogo({ constructorId }) {
  const logo = TEAM_LOGOS[constructorId?.toLowerCase()];

  if (!logo) {
    return <span className="standings-logo-slot" />;
  }

  return (
    <span className="standings-logo-slot">
      <img
        className="standings-team-logo"
        src={logo}
        alt=""
        onError={(event) => {
          event.currentTarget.style.visibility = "hidden";
        }}
      />
    </span>
  );
}

// Add your own Grand Prix images here later.
// The keys are Jolpica circuit IDs.
const RACE_IMAGES = {
  americas: "/races/united-states.webp",
};

function getSessionDate(session) {
  if (!session?.date || !session?.time) return null;

  const date = new Date(`${session.date}T${session.time}`);

  return Number.isNaN(date.getTime()) ? null : date;
}

function getWeekendSessions(race) {
  if (!race) return [];

  const types = [
    ["Practice 1", race.FirstPractice],
    ["Practice 2", race.SecondPractice],
    ["Practice 3", race.ThirdPractice],
    [
      "Sprint Qualifying",
      race.SprintQualifying || race.SprintShootout,
    ],
    ["Sprint", race.Sprint],
    ["Qualifying", race.Qualifying],
    ["Grand Prix", { date: race.date, time: race.time }],
  ];

  return types
    .map(([name, session]) => ({
      name,
      date: getSessionDate(session),
    }))
    .filter((session) => session.date)
    .sort((a, b) => a.date - b.date);
}

function getCountdown(milliseconds) {
  if (milliseconds <= 0) {
    return ["00", "00", "00", "00"];
  }

  const total = Math.floor(milliseconds / 1000);

  return [
    Math.floor(total / 86400),
    Math.floor((total % 86400) / 3600),
    Math.floor((total % 3600) / 60),
    total % 60,
  ].map((value) => String(value).padStart(2, "0"));
}

function App() {
  const [view, setView] = useState("dashboard");
  const [nextRace, setNextRace] = useState(null);
  const [raceError, setRaceError] = useState("");

  const [drivers, setDrivers] = useState([]);
  const [constructors, setConstructors] = useState([]);
  const [standingsError, setStandingsError] = useState("");
  const [standingsLoading, setStandingsLoading] = useState(true);
  const [standingsRound, setStandingsRound] = useState("");

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    async function loadRace() {
      try {
        const response = await fetch(
          `${API_BASE}/current/next.json`
        );

        if (!response.ok) {
          throw new Error("Unable to load the next race");
        }

        const data = await response.json();
        const race = data.MRData.RaceTable.Races[0];

        if (!race) {
          throw new Error("No upcoming race available");
        }

        setNextRace(race);
        setRaceError("");
      } catch (error) {
        setRaceError(error.message);
      }
    }

    loadRace();
  }, []);

  useEffect(() => {
    async function loadStandings() {
      try {
        const [driverResponse, constructorResponse] =
          await Promise.all([
            fetch(`${API_BASE}/current/driverstandings.json`),
            fetch(`${API_BASE}/current/constructorstandings.json`),
          ]);

        if (!driverResponse.ok || !constructorResponse.ok) {
          throw new Error("Unable to load standings");
        }

        const [driverData, constructorData] =
          await Promise.all([
            driverResponse.json(),
            constructorResponse.json(),
          ]);

        const driverList =
          driverData.MRData.StandingsTable.StandingsLists[0];

        const constructorList =
          constructorData.MRData.StandingsTable.StandingsLists[0];

        setDrivers(driverList?.DriverStandings || []);
        setConstructors(
          constructorList?.ConstructorStandings || []
        );

        setStandingsRound(driverList?.round || "");
        setStandingsError("");
      } catch (error) {
        setStandingsError(error.message);
      } finally {
        setStandingsLoading(false);
      }
    }

    loadStandings();
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const sessions = getWeekendSessions(nextRace);

  const raceStart = getSessionDate(
    nextRace
      ? { date: nextRace.date, time: nextRace.time }
      : null
  );

  const countdown = raceStart
    ? getCountdown(raceStart.getTime() - now)
    : null;

  const raceImage = nextRace
    ? RACE_IMAGES[nextRace.Circuit.circuitId]
    : null;

  const dateFormatter = new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  const timeFormatter = new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
  });

  return (
    <div className="app">
      <header className="header">
        <div className="branding">
          <span className="brand-accent">F1</span>
          <h1>RACE CENTER</h1>
        </div>

        <nav className="navigation">
          <button
            className={view === "dashboard" ? "active" : ""}
            onClick={() => setView("dashboard")}
          >
            Dashboard
          </button>

          <button
            className={view === "live" ? "active" : ""}
            onClick={() => setView("live")}
          >
            Live Race
          </button>
        </nav>
      </header>

      {view === "dashboard" ? (
        <main className="dashboard">
          {/* TOP LEFT: NEXT RACE */}
          <section
            className="display-panel race-panel"
            style={
              raceImage
                ? { "--race-photo": `url("${raceImage}")` }
                : {}
            }
          >
            <div className="panel-heading">
              <h2>NEXT GRAND PRIX</h2>
              <span className="panel-label">
                {nextRace ? `ROUND ${nextRace.round}` : "F1"}
              </span>
            </div>

            {raceError ? (
              <p className="status-message">{raceError}</p>
            ) : !nextRace ? (
              <p className="status-message">Loading race...</p>
            ) : (
              <>
                <div className="race-spacer" />

                <div className="race-info">
                  <h3>{nextRace.raceName}</h3>
                  <p>
                    {nextRace.Circuit.circuitName} ·{" "}
                    {nextRace.Circuit.Location.locality}
                  </p>
                </div>

                <div className="countdown-heading">
                  LIGHTS OUT IN
                </div>

                {countdown ? (
                  <div className="countdown-grid">
                    {["DAYS", "HRS", "MIN", "SEC"].map(
                      (label, index) => (
                        <div className="countdown-unit" key={label}>
                          <strong>{countdown[index]}</strong>
                          <small>{label}</small>
                        </div>
                      )
                    )}
                  </div>
                ) : (
                  <p>Race start time unavailable</p>
                )}
              </>
            )}
          </section>

          {/* TOP RIGHT: WEEKEND SCHEDULE */}
          <section className="display-panel schedule-panel">
            <div className="panel-heading">
              <h2>RACE WEEKEND</h2>
              <span className="panel-label">LOCAL TIME</span>
            </div>

            {raceError ? (
              <p className="status-message">{raceError}</p>
            ) : sessions.length ? (
              <div className="weekend-list">
                {sessions.map((session) => {
                  const isPast = session.date.getTime() < now;

                  return (
                    <div
                      className={`weekend-row ${
                        isPast ? "session-past" : ""
                      }`}
                      key={session.name}
                    >
                      <span className="session-name">
                        {session.name}
                      </span>
                      <span className="session-date">
                        {dateFormatter.format(session.date)}
                      </span>
                      <strong className="session-time">
                        {timeFormatter.format(session.date)}
                      </strong>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="status-message">
                Loading weekend schedule...
              </p>
            )}
          </section>

          {/* BOTTOM LEFT: TOP 10 DRIVERS */}
          <section className="display-panel drivers-panel">
            <div className="panel-heading">
              <h2>DRIVERS' STANDINGS</h2>
              <span className="panel-label">
                TOP 10 ·{" "}
                {standingsRound
                  ? `ROUND ${standingsRound}`
                  : "CHAMPIONSHIP"}
              </span>
            </div>

            {standingsLoading ? (
              <p className="status-message">Loading standings...</p>
            ) : standingsError ? (
              <p className="status-message">{standingsError}</p>
            ) : drivers.length === 0 ? (
              <p className="status-message">
                Standings not available yet
              </p>
            ) : (
              <div className="compact-standings">
                {drivers.slice(0, 10).map((driver) => {
                  const team = driver.Constructors?.[0];
                  const color = getTeamColor(
                    team?.constructorId
                  );

                  return (
                    <div
                    className={`compact-row ${
                      driver.Driver.driverId === "antonelli"
                        ? "team-background-test"
                        : ""
                    }`}
                    key={driver.Driver.driverId}
                    style={
                      driver.Driver.driverId === "antonelli"
                        ? {
                            "--team-background":
                              'url("/teams/mercedes.png")',
                          }
                        : {}
                    }
                  >
                      <span
                        className="team-accent"
                        style={{ backgroundColor: color }}
                      />

                      <strong className="rank">
                        {driver.position}
                      </strong>

                      <TeamLogo
                        constructorId={team?.constructorId}
                      />

                      <div className="competitor">
                        <strong>
                          {driver.Driver.givenName}{" "}
                          {driver.Driver.familyName}
                        </strong>
                        <small>{getTeamName(team)}</small>
                      </div>

                      <strong className="points">
                        {driver.points}
                      </strong>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* BOTTOM RIGHT: CONSTRUCTORS */}
          <section className="display-panel constructors-panel">
            <div className="panel-heading">
              <h2>CONSTRUCTORS' STANDINGS</h2>
              <span className="panel-label">ALL TEAMS</span>
            </div>

            {standingsLoading ? (
              <p className="status-message">Loading standings...</p>
            ) : standingsError ? (
              <p className="status-message">{standingsError}</p>
            ) : constructors.length === 0 ? (
              <p className="status-message">
                Standings not available yet
              </p>
            ) : (
              <div className="compact-standings">
                {constructors.map((team) => (
                  <div
                    className="compact-row"
                    key={team.Constructor.constructorId}
                  >
                    <span
                      className="team-accent"
                      style={{
                        backgroundColor: getTeamColor(
                          team.Constructor.constructorId
                        ),
                      }}
                    />

                    <strong className="rank">
                      {team.position}
                    </strong>

                    <TeamLogo
                      constructorId={
                        team.Constructor.constructorId
                      }
                    />

                    <div className="competitor">
                      <strong>
                        {getTeamName(team.Constructor)}
                      </strong>
                    </div>

                    <strong className="points">
                      {team.points}
                    </strong>
                  </div>
                ))}
              </div>
            )}
          </section>
        </main>
      ) : (
        <LiveRace />
      )}
    </div>
  );
}

export default App;
