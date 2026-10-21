
function validTime(value) {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

export function buildRetirementTimes({
  raceControl = [],
  sessionResults = [],
  laps = [],
  locations = {},
}) {
  const retirements = {};
  const completedLapEnds = {};

  // Determine the end of each driver's last completed lap.
  for (const lap of laps) {
    const number = Number(lap.driver_number);
    const start = validTime(lap.date_start);
    const duration = Number(lap.lap_duration);

    if (
      !Number.isFinite(number) ||
      number <= 0 ||
      start === null ||
      !Number.isFinite(duration) ||
      duration <= 0
    ) {
      continue;
    }

    const end = start + duration * 1000;

    completedLapEnds[number] = Math.max(
      completedLapEnds[number] ?? -Infinity,
      end
    );
  }

  // Detect explicit race-control retirement announcements.
  for (const event of raceControl) {
    const message = String(event.message || "").toUpperCase();
    const time = validTime(event.date);

    const explicitNumber = Number(event.driver_number);
    const match = message.match(/\bCAR\s+(\d{1,2})\b/);

    const number =
      explicitNumber > 0
        ? explicitNumber
        : match
          ? Number(match[1])
          : null;

    const isRetirement =
      /\bRETIRED\b/.test(message) ||
      /\bRETIREMENT\b/.test(message) ||
      /\bWILL NOT RESTART\b/.test(message);

    if (
      !isRetirement ||
      number === null ||
      time === null
    ) {
      continue;
    }

    retirements[number] = Math.min(
      retirements[number] ?? Infinity,
      time
    );
  }

  // Estimate retirement times for confirmed DNFs
  // when race control has no explicit announcement.
  for (const result of sessionResults) {
    if (result.dnf !== true) continue;

    const number = Number(result.driver_number);

    if (
      !Number.isFinite(number) ||
      number <= 0 ||
      retirements[number] !== undefined
    ) {
      continue;
    }

    const lastLapEnd = completedLapEnds[number];

    if (!Number.isFinite(lastLapEnd)) continue;

    const points = locations[number] || [];

    // Provisional search window after the last completed lap.
    const cutoff = lastLapEnd + 3 * 60 * 1000;

    let lastGPS = null;

    for (const point of points) {
      if (
        Number.isFinite(point.time) &&
        point.time >= lastLapEnd - 30000 &&
        point.time <= cutoff
      ) {
        lastGPS = Math.max(
          lastGPS ?? -Infinity,
          point.time
        );
      }
    }

    retirements[number] =
      lastGPS !== null
        ? Math.max(lastLapEnd, lastGPS)
        : lastLapEnd;
  }

  return retirements;
}
