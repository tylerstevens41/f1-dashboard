
import fs from "node:fs/promises";
import path from "node:path";

const API = "https://api.openf1.org/v1";
const OUTPUT = path.resolve(
  "public/data/austin-2026-race.json"
);

// GPS sampling interval in milliseconds.
// 1000 keeps the replay file manageable.
const SAMPLE_MS = 1000;
const WINDOW_MS = 10 * 60 * 1000;

const sleep = (ms) =>
  new Promise((resolve) => setTimeout(resolve, ms));

async function request(endpoint, params = {}) {
  const url = new URL(`${API}/${endpoint}`);

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }

  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      const response = await fetch(url, {
        signal: AbortSignal.timeout(60000),
      });

      if (!response.ok) {
        throw new Error(
          `${endpoint}: HTTP ${response.status}`
        );
      }

      return await response.json();
    } catch (error) {
      if (attempt === 5) throw error;

      console.log(
        `Retry ${attempt}/5: ${error.message}`
      );

      await sleep(attempt * 1500);
    }
  }
}

function timestamp(value) {
  return Date.parse(value);
}

function sampleLocations(records) {
  const output = [];
  let lastBucket = -1;

  for (const point of records) {
    const time = timestamp(point.date);
    const bucket = Math.floor(time / SAMPLE_MS);

    if (!Number.isFinite(time)) continue;
    if (!Number.isFinite(Number(point.x))) continue;
    if (!Number.isFinite(Number(point.y))) continue;
    if (bucket === lastBucket) continue;

    lastBucket = bucket;

    output.push([
      time,
      Number(point.x),
      Number(point.y),
    ]);
  }

  return output;
}

async function main() {
  console.log("Finding 2026 Austin Grand Prix...");

  const sessions = await request("sessions", {
    year: 2026,
    session_name: "Race",
  });

  const session = sessions.find((item) => {
    const text = [
      item.country_name,
      item.location,
      item.circuit_short_name,
      item.meeting_name,
    ]
      .join(" ")
      .toLowerCase();

    return (
      text.includes("united states") ||
      text.includes("austin") ||
      text.includes("americas")
    );
  });

  if (!session) {
    throw new Error(
      "Austin 2026 Race session was not found. " +
      "Check OpenF1 session availability."
    );
  }

  console.log(
    `Found session ${session.session_key}`
  );

  const sessionKey = session.session_key;

  const [
    drivers,
    laps,
    positions,
    stints,
    raceControl,
    intervals,
  ] = await Promise.all([
    request("drivers", { session_key: sessionKey }),
    request("laps", { session_key: sessionKey }),
    request("position", { session_key: sessionKey }),
    request("stints", { session_key: sessionKey }),
    request("race_control", { session_key: sessionKey }),
    request("intervals", { session_key: sessionKey }),
  ]);

  const start = timestamp(session.date_start);
  const end = timestamp(session.date_end);

  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    end <= start
  ) {
    throw new Error(
      "Session start/end times are unavailable."
    );
  }

  const locations = {};

  for (const driver of drivers) {
    const number = String(driver.driver_number);
    const allPoints = [];

    console.log(
      `Downloading GPS for ${driver.name_acronym} (#${number})`
    );

    for (
      let from = start;
      from < end;
      from += WINDOW_MS
    ) {
      const to = Math.min(from + WINDOW_MS, end);

      const records = await request("location", {
        session_key: sessionKey,
        driver_number: number,
        "date>": new Date(from).toISOString(),
        "date<": new Date(to).toISOString(),
      });

      allPoints.push(...records);

      await sleep(150);
    }

    allPoints.sort(
      (a, b) =>
        timestamp(a.date) - timestamp(b.date)
    );

    locations[number] = sampleLocations(allPoints);

    console.log(
      `  Saved ${locations[number].length} samples`
    );
  }

  // Generate circuit geometry from one complete
  // timed lap, using the SAME coordinate system
  // as the downloaded driver positions.
  let reference = [];

  for (const driver of drivers) {
    const number = String(driver.driver_number);

    const validLaps = laps
      .filter(
        (lap) =>
          String(lap.driver_number) === number &&
          lap.lap_number >= 2 &&
          lap.date_start &&
          Number(lap.lap_duration) > 50 &&
          Number(lap.lap_duration) < 250
      )
      .sort(
        (a, b) =>
          a.lap_number - b.lap_number
      );

    for (const lap of validLaps) {
      const lapStart = timestamp(lap.date_start);
      const lapEnd =
        lapStart + lap.lap_duration * 1000;

      const points = locations[number].filter(
        (point) =>
          point[0] >= lapStart &&
          point[0] <= lapEnd
      );

      if (points.length >= 40) {
        reference = points.map(
          ([, x, y]) => ({ x, y })
        );

        break;
      }
    }

    if (reference.length) break;
  }

  if (!reference.length) {
    throw new Error(
      "Could not build a full-lap GPS reference. " +
      "Check the downloaded location and lap data."
    );
  }

  const output = {
    metadata: {
      source: "OpenF1",
      session_key: sessionKey,
      name: session.meeting_name,
      circuit: "Austin",
      date_start: session.date_start,
      date_end: session.date_end,
      sample_ms: SAMPLE_MS,
    },
    drivers,
    reference,
    locations,
    laps,
    positions,
    stints,
    raceControl,
    intervals,
  };

  await fs.mkdir(path.dirname(OUTPUT), {
    recursive: true,
  });

  await fs.writeFile(
    OUTPUT,
    JSON.stringify(output)
  );

  console.log("");
  console.log("Replay download complete!");
  console.log(`Saved to ${OUTPUT}`);
  console.log(`Drivers: ${drivers.length}`);
  console.log(`Track points: ${reference.length}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
