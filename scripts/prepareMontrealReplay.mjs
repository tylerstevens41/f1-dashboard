
import fs from "node:fs/promises";
import path from "node:path";

const DATA_DIR = path.join(
  "public",
  "data",
  "montreal-2026-race"
);

const SAMPLE_INTERVAL_MS = 1000;

const inputPath = path.join(DATA_DIR, "locations.json");
const outputPath = path.join(
  DATA_DIR,
  "locations-replay.json"
);

console.log("======================================");
console.log("PREPARING 2026 MONTREAL RACE REPLAY");
console.log("======================================");

const sessions = JSON.parse(
  await fs.readFile(
    path.join(DATA_DIR, "session.json"),
    "utf8"
  )
);

const session = sessions.find(
  (item) => Number(item.session_key) === 11291
);

if (!session) {
  throw new Error("Montreal race session not found.");
}

const sessionStart = Date.parse(session.date_start);

if (!Number.isFinite(sessionStart)) {
  throw new Error("Invalid session start time.");
}

console.log(`Session start: ${session.date_start}`);
console.log("Reading original location data...");

const raw = JSON.parse(
  await fs.readFile(inputPath, "utf8")
);

console.log(`Original records: ${raw.length}`);

const grouped = new Map();

for (const point of raw) {
  const timestamp = Date.parse(point.date);
  const driverNumber = Number(point.driver_number);

  if (
    !Number.isFinite(timestamp) ||
    timestamp < sessionStart ||
    !Number.isFinite(driverNumber) ||
    !Number.isFinite(point.x) ||
    !Number.isFinite(point.y) ||
    (point.x === 0 && point.y === 0)
  ) {
    continue;
  }

  if (!grouped.has(driverNumber)) {
    grouped.set(driverNumber, []);
  }

  grouped.get(driverNumber).push({
    driver_number: driverNumber,
    time: timestamp,
    x: point.x,
    y: point.y,
  });
}

const optimized = [];

for (const [driverNumber, points] of grouped) {
  points.sort((a, b) => a.time - b.time);

  let lastSavedTime = -Infinity;
  let saved = 0;

  for (const point of points) {
    if (
      point.time - lastSavedTime >= SAMPLE_INTERVAL_MS
    ) {
      optimized.push(point);
      lastSavedTime = point.time;
      saved++;
    }
  }

  console.log(
    `Driver #${driverNumber}: ${points.length} → ${saved} records`
  );
}

optimized.sort((a, b) => a.time - b.time);

if (optimized.length === 0) {
  throw new Error(
    "No usable replay records found after session start."
  );
}

await fs.writeFile(
  outputPath,
  JSON.stringify(optimized),
  "utf8"
);

const originalSize = (
  (await fs.stat(inputPath)).size / 1024 / 1024
).toFixed(2);

const optimizedSize = (
  (await fs.stat(outputPath)).size / 1024 / 1024
).toFixed(2);

const reduction = (
  (1 - Number(optimizedSize) / Number(originalSize)) * 100
).toFixed(1);

console.log("");
console.log("======================================");
console.log("MONTREAL REPLAY PREPARED!");
console.log("======================================");
console.log(`Original records: ${raw.length}`);
console.log(`Replay records: ${optimized.length}`);
console.log(`Drivers with locations: ${grouped.size}`);
console.log(`Original size: ${originalSize} MB`);
console.log(`Replay size: ${optimizedSize} MB`);
console.log(`Size reduction: ${reduction}%`);
console.log(
  `First replay location: ${new Date(optimized[0].time).toISOString()}`
);
console.log(
  `Last replay location: ${new Date(optimized.at(-1).time).toISOString()}`
);
console.log(`Saved to: ${outputPath}`);
