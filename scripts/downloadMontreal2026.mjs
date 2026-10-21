
import fs from "node:fs/promises";
import path from "node:path";

const API = "https://api.openf1.org/v1";
const OUTPUT = path.join(
  "public",
  "data",
  "montreal-2026-race"
);

const DELAY_MS = 5000;
const MAX_ATTEMPTS = 5;

await fs.mkdir(OUTPUT, { recursive: true });

const sleep = (ms) =>
  new Promise((resolve) => setTimeout(resolve, ms));

async function request(endpoint, params = {}) {
  const url = new URL(`${API}/${endpoint}`);

  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, String(value));
  }

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    console.log(
      `GET ${endpoint} (attempt ${attempt}/${MAX_ATTEMPTS})`
    );

    try {
      const response = await fetch(url);

      if (response.status === 429 || response.status >= 500) {
        const retryAfter = Number(
          response.headers.get("retry-after")
        );

        const waitMs =
          response.status === 429 &&
          Number.isFinite(retryAfter) &&
          retryAfter > 0
            ? Math.min(retryAfter * 1000, 180000)
            : attempt * 20000;

        console.log(
          `HTTP ${response.status}. Waiting ${waitMs / 1000}s...`
        );

        await sleep(waitMs);
        continue;
      }

      if (!response.ok) {
        throw new Error(
          `${endpoint}: HTTP ${response.status}`
        );
      }

      const data = await response.json();

      if (!Array.isArray(data)) {
        throw new Error(
          `Unexpected response from ${endpoint}`
        );
      }

      await sleep(DELAY_MS);
      return data;
    } catch (error) {
      if (attempt === MAX_ATTEMPTS) throw error;

      console.log(`Error: ${error.message}`);
      await sleep(attempt * 15000);
    }
  }

  throw new Error(`Unable to download ${endpoint}`);
}

async function readSaved(filename) {
  try {
    const contents = await fs.readFile(
      path.join(OUTPUT, filename),
      "utf8"
    );

    const data = JSON.parse(contents);
    return Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}

async function save(filename, data) {
  await fs.writeFile(
    path.join(OUTPUT, filename),
    JSON.stringify(data),
    "utf8"
  );

  console.log(
    `Saved ${filename}: ${data.length} records`
  );
}

async function getDataset(
  endpoint,
  filename,
  sessionKey,
  additionalParams = {}
) {
  const existing = await readSaved(filename);

  if (existing !== null) {
    console.log(`Already downloaded: ${filename}`);
    return existing;
  }

  const data = await request(endpoint, {
    session_key: sessionKey,
    ...additionalParams,
  });

  await save(filename, data);
  return data;
}

console.log("======================================");
console.log("2026 CANADIAN GRAND PRIX DOWNLOADER");
console.log("======================================");

// Find the race automatically, without hardcoding
// a session key that could be incorrect.

const sessions = await request("sessions", {
  year: 2026,
  session_name: "Race",
});

const race = sessions.find((session) => {
  const country = String(
    session.country_name || ""
  ).toLowerCase();

  const location = String(
    session.location || ""
  ).toLowerCase();

  return (
    country.includes("canada") ||
    location.includes("montreal") ||
    location.includes("montréal")
  );
});

if (!race) {
  throw new Error(
    "Could not find the 2026 Canadian Grand Prix race session."
  );
}

const SESSION_KEY = race.session_key;

console.log("");
console.log(`Race: ${race.session_name}`);
console.log(`Circuit: ${race.circuit_short_name}`);
console.log(`Session key: ${SESSION_KEY}`);
console.log(`Start: ${race.date_start}`);
console.log(`End: ${race.date_end}`);
console.log("");

await fs.writeFile(
  path.join(OUTPUT, "session.json"),
  JSON.stringify([race]),
  "utf8"
);

// Download the datasets used by the Race Center.

const datasets = [
  ["drivers", "drivers.json"],
  ["position", "positions.json"],
  ["laps", "laps.json"],
  ["intervals", "intervals.json"],
  ["stints", "stints.json"],
  ["pit", "pit.json"],
  ["race_control", "race_control.json"],
  ["weather", "weather.json"],
  ["session_result", "session_result.json"],
];

for (const [endpoint, filename] of datasets) {
  await getDataset(
    endpoint,
    filename,
    SESSION_KEY
  );
}

// Download locations one driver at a time.
// This avoids the date-filter HTTP 500 errors
// encountered during the Singapore download.

const drivers = await readSaved("drivers.json");

if (!drivers?.length) {
  throw new Error("No drivers found for this race");
}

const allLocations = [];

for (let index = 0; index < drivers.length; index++) {
  const driver = drivers[index];
  const number = driver.driver_number;

  console.log("");
  console.log(
    `DRIVER ${index + 1}/${drivers.length}: ` +
    `${driver.name_acronym} (#${number})`
  );

  const filename = `location-driver-${number}.json`;

  const locations = await getDataset(
    "location",
    filename,
    SESSION_KEY,
    { driver_number: number }
  );

  allLocations.push(...locations);

  console.log(
    `Driver ${number}: ${locations.length} locations`
  );
}

console.log("");
console.log("Combining location data...");

allLocations.sort(
  (a, b) => Date.parse(a.date) - Date.parse(b.date)
);

await save("locations.json", allLocations);

console.log("");
console.log("======================================");
console.log("MONTREAL 2026 DOWNLOAD COMPLETE!");
console.log("======================================");
console.log(`Session key: ${SESSION_KEY}`);
console.log(`Drivers: ${drivers.length}`);
console.log(
  `Total location records: ${allLocations.length}`
);
console.log(
  `First location: ${allLocations[0]?.date || "N/A"}`
);
console.log(
  `Last location: ${allLocations.at(-1)?.date || "N/A"}`
);
console.log(`Saved to: ${OUTPUT}`);
