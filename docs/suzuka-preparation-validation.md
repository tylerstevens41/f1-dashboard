# Suzuka validation using the shared preparation pipeline

Status: real-data preparation is **not validated in this checkout**. A 2026
LiveF1 session-index request returned `ArchiveUnavailable`, code
`authentication-required`. No real Suzuka session, window, GPS count, calibration
metric, corner count or timing boundary was obtained. Do not interpret synthetic
figure-eight tests as evidence that Suzuka is ready. No new circuit assets or
telemetry caches are committed.

## Findings and focused changes

Geometry reconstruction already groups by driver/lap, sorts by source timestamp,
resamples each ordered loop, aligns only cyclic phase (never reverses laps), then
uses a pointwise median and ordered smoothing. It does not construct connectivity
from nearest XY neighbors. Crossovers remain separate visits in the path sequence.
Nearest-segment metrics are shape-error diagnostics, not proof of track order.

One generic preparation guard previously required nonzero signed enclosed area
with matching signs across laps. Oppositely oriented lobes can cancel in a valid
figure-eight. The guard now retains its original behavior when areas agree, but
otherwise compares full cyclic ordered trajectories against forward and reversed
reference order. Reversed or ambiguous laps still fail. This changes neither
coordinate calibration nor geometry smoothing, accuracy thresholds, sector math,
annotation source, driver motion or rendering. The fallback's direction evidence
is recorded under `orderedDirection` in per-window diagnostics.

FastF1 full-lap registration and corner/boundary projection keep their existing
ambiguity checks: if a crossing cannot be assigned confidently, annotations fail
provisionally while geometry survives. No nearest-branch guess is added. The
same public importer, multi-lap timing calculation, calculated-boundary selection,
registry, rendering and collision-layout functions apply without Suzuka branches.
Existing Austin-specific official references remain explicit reference inputs;
Suzuka does not inherit Austin's FIA checks. A projected intersection does not
verify bridge height or independently establish physical track topology.

The bounded Windows replacement retry is now shared by annotation/progress files
and circuit immutable revision/current-pointer writes. There are no extra network
retries, timeout increases, alternate authentication methods or silent session
substitutions.

## Windows: prepare the newest season's Japanese Race

Run from the repository root. Keep `.venv` and `.venv-fastf1` separate. The
commands select **2026 / Japan / Race as a candidate**, resolving the actual
published event, circuit key and path from LiveF1 metadata; no path is guessed.
A past published race is not proof that every required topic is complete.

```powershell
git switch feat/automatic-circuit-preparation
git pull --ff-only origin feat/automatic-circuit-preparation

# If FastF1's local token needs renewal, do this interactively:
.\.venv-fastf1\Scripts\python.exe -m fastf1 auth f1tv --authenticate

# Existing shared coordinator discovers identity and bounded usable GPS windows:
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Japan --session Race --login

# Read-only audit: use a fresh filename on each run to preserve evidence:
.\.venv\Scripts\python.exe -m bridge.preparation_audit --year 2026 --event Suzuka --report .\suzuka-audit-01.json
$audit = Get-Content .\suzuka-audit-01.json -Raw | ConvertFrom-Json
$audit.circuits | ConvertTo-Json -Depth 30
```

No manually chosen offset is necessary for preparation. Existing coverage/usable
GPS discovery is bounded and requires normal complete-lap/calibration checks.
If 2026 is unavailable, inspect the actual safe failure first. An explicit earlier
season can be tested with the same command and `--year 2025`; do not silently
substitute it or label a 2025 mapping compatible with 2026 LIVE data. Circuit
key/season/layout identity and runtime compatibility checks remain enforced.

If only annotations are incomplete, preserve geometry and retry:

```powershell
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Japan --session Race --annotations-only --login
```

The audit records the actual `identity`, `gps` counts/rejection reasons,
`calibration.heldOut`, `annotations.registration`, all three calculated boundary
fractions, source accuracy/precision diagnostics and `crossover.projectedCrossings`.
It reads existing assets only and refuses to overwrite a report. It does not
perform a FastF1 request, select another session, approve annotations or alter
manual overrides.

## Storage and playback settings

The existing store remains `circuit-assets/circuit-<published-key>-2026/` with an
immutable revision JSON and `current.json` pointer. The audit's `assets` field
identifies the actual directory. It contains `job.json`, geometry diagnostics and
annotation diagnostics/checkpoints. Shared caches remain `circuit-assets/gps-cache`,
`circuit-assets/fastf1-cache` and `circuit-assets/annotation-sources`. No cleanup or
regeneration of Austin/Mexico assets is required.

```powershell
$prepared = $audit.circuits | Select-Object -First 1
$prepared.identity
$prepared.testPlayback
if ($prepared) {
    Get-Content (Join-Path $prepared.assets 'geometry-diagnostics.json') -Raw
    Get-Content (Join-Path $prepared.assets 'annotation-diagnostics.json') -Raw
}
```

`testPlayback.sessionPath` and `offsetSeconds` come from the saved identity and
accepted preparation window, with clip duration **480 seconds** and initial speed
**1x**. These are reproducible local TEST candidates, not verified playback
settings: the preparation window uses geometry topics, while full TEST also
requests the dashboard's other topics. No exact Suzuka offset can be supplied
honestly until the authenticated preparation succeeds. Do not use Austin/Mexico
clock offsets for Suzuka.

Start the backend and frontend in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --idle --allow-test --allow-prepare --login
```

```powershell
npm run dev
```

In TEST controls choose the audit's exact season/event/Race session and accepted
offset, clip length 480, speed 1x. Prepared geometry should load via the dynamic
registry. Verify cars stay on the correct branch at both crossover visits, follow
the whole lap in source order and wrap correctly at start/finish. Inspect actual
numbered corners, label collision warnings, charcoal base and magenta/yellow/cyan
transitions; compare with authoritative circuit references before marking anything
verified. Test pause/resume and 2x/5x playback, then the existing Austin/Mexico clips.
Do not mark completion solely from the preparation flag or passing unit tests.

## Automated evidence and remaining limitations

Synthetic tests cover cancelling-area direction, reversed laps, cyclic origins,
ordered crossover reconstruction and held-out checks, cached coordinator geometry,
shared registration and unequal timing-based boundaries on a figure-eight fixture,
ambiguous crossover projection rejection, synthetic-publication rejection, and
read-only audit behavior. JavaScript tests preserve separate fraction/tangent
visits at the same XY location and stable label priorities without anchor edits.
Existing checkpoint, missing-data, Windows-lock, shared Austin/Mexico renderer,
source-clock, animation and TEST/LIVE tests remain in the normal suites.

Real source access, selected Suzuka session completeness, physical crossover
order, GPS alignment, exact corner count, timing-line accuracy and screenshots
remain unverified. The milestone is incomplete until the local preparation,
report and visual playback checks succeed.
