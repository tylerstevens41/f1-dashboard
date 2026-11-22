# Las Vegas 2026: urgent local circuit preparation

## Finding and present limitation

`older-source-found-layout-compatibility-unverified` comes from
`season_preparation.run`: no eligible target-season session was found, older
sessions were found, and the coordinator deliberately refused cross-season reuse.
An eligible archive is published in the provider index, matches venue identity,
and passes its six-hour age gate. The new targeted command interprets provider
GMT offsets explicitly and excludes unknown timezones. The older season
batch also caches catalogs for 24 hours and persists retry backoff; a report from
before this weekend does not demonstrate today's archive availability.

The checkout's November 7 report is a different run: its Vegas row records a
sanitized authentication failure/retry backoff. Do not mistake it for the user's
local older-source report. A fresh LiveF1 archive probe here still returned
`authentication-required`. A bounded 15-second FastF1 qualifying probe separately reached its HTTP stage
and failed with `fastf1-authentication-required`; it did not load real laps.
No 2026 Vegas positions, qualifying laps, corners,
sector estimates or calibrated assets have been obtained in this environment.

## Immediate Windows procedure

Stop old application processes with Ctrl+C. From the repository:

```powershell
git fetch origin
git switch feat/production-live-ui-cleanup
git pull --ff-only origin feat/production-live-ui-cleanup
.\.venv\Scripts\python.exe -m bridge.event_preparation --year 2026 --event "Las Vegas" --geometry-only --login
```

This queries the fresh 2026 provider catalog, excludes future/too-recent sessions,
uses real circuit keys/paths, prefers an eligible Race then newest qualifying or
practice, and never substitutes 2025 geometry. It rejects ambiguous circuit keys
and unknown timezone metadata. Six-hour eligibility is conservative, not proof
that a delayed session ended: measured complete laps and all calibration checks
still must pass. If the newest archive is unusable, other eligible sessions from
the same year/circuit are tried. Authentication failure stops the attempts.

The new command bypasses season queue backoff/catalog caches; it does not edit or
reset that queue. It scans from the archive's beginning for measured lap numbers
and moving on-track GPS, then passes the observed offset into the **unchanged**
shared complete-lap collector/build/held-out/direction/spatial-coverage checks.
It does not ask for guessed offsets. Geometry-only returns before FastF1 work.
Existing valid geometry is reused without rewriting its pointer.

After `geometry-ready`, generate the annotations (if time allows):

```powershell
.\.venv\Scripts\python.exe -m bridge.event_preparation --year 2026 --event "Las Vegas" --annotations-only --login
```

This resumes the original geometry source, uses the existing `.venv-fastf1`
worker and Austin/Mexico corner/sector functions, and never recollects geometry.
Keep `.venv` and `.venv-fastf1` separate. If needed, install importer requirements
only with `.\.venv-fastf1\Scripts\python.exe -m pip install -r bridge/requirements-corners.txt`.
If the annotation diagnostic explicitly reports `fastf1-authentication-required`,
authenticate locally in the separate importer environment, then retry:

```powershell
.\.venv-fastf1\Scripts\python.exe -m fastf1 auth f1tv --authenticate
```

Source caches and completed annotation checkpoints remain reusable. A failed
annotation stage retains geometry and completed annotations.

Start the dashboard using the same circuit store:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --auto --login
```

In a second terminal:

```powershell
npm run dev
```

Open http://localhost:5173/dev to inspect controller/circuit status, then
http://localhost:5173/wall. AUTO must be explicitly selected if a persisted MANUAL
mode was previously chosen. `/dev` is not required to stay open. If the backend
was running during preparation, its existing AUTO asset lookup refreshes within
60 seconds; a backend/browser restart also reloads assets. Actual LIVE session
metadata determines circuit key/year, so qualifying geometry can resolve for
Race without a guessed path. Runtime GPS compatibility remains mandatory.

If AUTO cannot discover the race, use `/dev` → MANUAL → Discover race sessions →
select the actual published Las Vegas Race → Start LIVE. Never load an archive
as a substitute for LIVE. If no compatible geometry can be prepared, keep the
LIVE timing tower/race-control information and withhold unvalidated car markers.
Geometry-only can display the accepted outline/positions after runtime validation;
corners, start/finish and sector colours wait for genuine annotation completion.

## Inspect evidence without redownloading

```powershell
$run = Get-ChildItem .\circuit-assets\event-runs\las-vegas-2026-*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$report = Get-Content $run.FullName -Raw | ConvertFrom-Json
$report | ConvertTo-Json -Depth 30
$asset = $report.audit.assets
if (-not $asset -and $report.attempts.Count -gt 0) { $asset = Join-Path '.\circuit-assets' $report.attempts[-1].identity.assetKey }
if ($asset) {
  Get-Content (Join-Path $asset 'job.json') -Raw
  if (Test-Path (Join-Path $asset 'geometry-diagnostics.json')) { Get-Content (Join-Path $asset 'geometry-diagnostics.json') -Raw }
  if (Test-Path (Join-Path $asset 'annotation-diagnostics.json')) { Get-Content (Join-Path $asset 'annotation-diagnostics.json') -Raw }
}
```

New run files are uniquely named; prior reports and reviewed assets are retained.
The audit includes selected session, measured window, sample/lap counts, rejected
laps, held-out calibration metrics, geometry fingerprint, source directories,
corner count and timing-boundary estimates. Source telemetry caches remain local.
To test the accepted source before LIVE, restart backend in developer mode:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --manual --idle --allow-test --login
```

In `/dev` choose the **exact source session** from `$report.selectedSession` and
use `$report.audit.testPlayback.offsetSeconds`, duration 480, speed 1. These are
accepted calibration footage settings, not a claim of visually verified playback.
Confirm shape, direction, S/F and marker alignment before switching back to AUTO.

## Independent FIA evidence and remaining checks

Official FIA 2026 Document 5, November 18, lists kerb/lighting/manhole/asphalt work
and pit-entry wall realignment. This supports investigating continuity, but is
**not** proof that 2025 raw GPS, registration or annotation coordinates transfer.
This workflow intentionally does not authorize older assets from that evidence.

- Competition notes: https://www.fia.com/system/files/decision-document/2026_las_vegas_grand_prix_-_race_directors_competition_notes.pdf
- Document 6 map (version 1, issued November 14): https://www.fia.com/system/files/decision-document/2026_las_vegas_grand_prix_-_competition_notes_-_circuit_map_pit_lane_drawing_emergency_exits_map_and_red_zone.pdf

The 2026 map lists a 6.201 km centreline, 17 turns, sectors 1.693/1.735/2.773 km,
intermediate 1 at 90 m after T5 and intermediate 2 at 170 m after T12. Use these
as independent coarse checks, not forced GPS path fractions or coordinates.
Distinguish the control/timing line from the separate grid start line. Nothing
in this change invents annotation fractions or marks them verified.

Until local preparation succeeds, geometry/calibration/2026 compatibility and
annotations remain **unverified**. SVG/dynamic registry and AUTO resolution are
covered by synthetic regressions, not real Vegas telemetry. LIVE marker alignment,
provider cadence, interpolation and visual fit must be observed locally; their
existing implementation is unchanged.
