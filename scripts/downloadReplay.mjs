
import fs from "node:fs/promises";
import path from "node:path";

const SESSION_KEY = 9161;
const START = "2023-09-16T13:03:35";
const END = "2023-09-16T13:05:35";

const OUTPUT_DIR = path.join("public", "data");
const API = "https://api.openf1.org/v1";

await fs.mkdir(OUTPUT_DIR, { recursive: true });

const downloads = [
  {
    endpoint: "drivers",
    filename: "drivers.json",
    params: { session_key: SESSION_KEY },
  },
  {
    endpoint: "position",
    filename: "positions.json",
    params: { session_key: SESSION_KEY },
  },
  {
    endpoint: "laps",
    filename: "laps.json",
    params: { session_key: SESSION_KEY },
  },
  {
    endpoint: "location",
    filename: "locations.json",
    params: {
      session_key: SESSION_KEY,
      "date>": START,
      "date<": END,
    },
  },
];

const delay = (ms) =>
  new Promise((resolve) => setTimeout(resolve, ms));

async function download({ endpoint, filename, params }) {
  const url = new URL(`${API}/${endpoint}`);

  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, String(value));
  }

  const outputPath = path.join(OUTPUT_DIR, filename);

  // Reuse successful downloads on subsequent runs.
  try {
    const existing = JSON.parse(
      await fs.readFile(outputPath, "utf8")
    );

    if (Array.isArray(existing) && existing.length > 0) {
      console.log(`Already saved: ${filename}`);
      return;
    }
  } catch {
    // File does not exist or is not valid JSON.
  }

  for (let attempt = 1; attempt <= 3; attempt++) {
    console.log(`Downloading ${filename} (attempt ${attempt})...`);

    const response = await fetch(url);

    if (response.status === 429) {
      const retryAfter = response.headers.get("retry-after");

      const seconds = retryAfter
        ? Number(retryAfter)
        : NaN;

      const waitMs = Number.isFinite(seconds)
        ? Math.min(Math.max(seconds * 1000, 1000), 120000)
        : 30000 * attempt;

      console.log(
        `Rate limited. Waiting ${Math.round(waitMs / 1000)}s...`
      );

      await delay(waitMs);
      continue;
    }

    if (!response.ok) {
      throw new Error(
        `${filename}: HTTP ${response.status}`
      );
    }

    const data = await response.json();

    if (!Array.isArray(data) || data.length === 0) {
      throw new Error(
        `${filename}: No records returned. File not saved.`
      );
    }

    await fs.writeFile(
      outputPath,
      JSON.stringify(data),
      "utf8"
    );

    console.log(`Saved ${filename}: ${data.length} records`);
    return;
  }

  throw new Error(
    `Could not download ${filename}. OpenF1 is still rate limiting requests.`
  );
}

for (const item of downloads) {
  await download(item);

  // Space out successful requests.
  await delay(5000);
}

console.log("Historical replay data is ready!");
