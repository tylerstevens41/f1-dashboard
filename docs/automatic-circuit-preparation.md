# Automatic circuit preparation (stacked draft PR)

This extends PR #5. Austin continues using its existing `public/circuits/austin-*.json` files and browser overrides. No Austin assets are replaced. Mexico is the first intended real-data validation; the automated tests use explicitly synthetic fixtures. No Mexico layout is bundled or claimed accurate. An archive listing attempt in the implementation environment returned `ArchiveUnavailable`; real Mexico processing could not proceed. Browser visual verification and Windows-native execution were unavailable here; both require local review.

## How it works

The archive index supplies the stable circuit key, event and session metadata. A circuit key plus source season identifies a candidate layout. Event-name aliases with the same key share assets; a different year never silently reuses them. Actual within-season layout/coordinate differences still require the incoming-GPS compatibility check and local review. A season key is not proof that every session used identical geometry.

The coordinator reuses `calibrate.clean_laps` and `calibrate.build`: three complete non-pit laps minimum, finite/stale/spike/gap/closure checks, held-out residuals, and a maximum spatial step check. The optional original-SVG comparison is omitted for a new track, not replaced with a FastF1 outline. Geometry and cars use measured LiveF1 native coordinates, with display inversion applied separately by the existing renderer. Driving order is retained; a reversed FastF1 registration is rejected.

Up to three **480 second windows**, initially at archive offsets **5400, 6000 and 3600 seconds**, are attempted within the explicitly selected session. These are source-stream offsets, not lights-out times. The CLI can specify up to five different windows; it does not guess a different season or layout. An unusable session fails clearly; select another published session and retry. There is no automatic older-season substitution.

A writable `circuit-assets/` directory holds immutable revision JSON files, an atomically replaced current pointer, and per-circuit job progress. This is ignored by Git. Geometry is published first. A separately invoked `.venv-fastf1` worker retrieves/caches corners and multi-lap timing/position information, reuses the existing registration and sector calculation, and fills missing annotation assets. Missing annotations leave geometry usable. Existing annotation records are never replaced on retry. Manual/browser overrides remain keyed to circuit/layout/geometry. Existing calculation-default/source-selection rules apply unchanged.

No full-season recordings are saved: normalized GPS cache is capped at 128 MiB, normalized FastF1 source cache at 128 MiB, and FastF1's disposable cache at 512 MiB. Pruning occurs between attempts/imports. A single FastF1 session load may temporarily exceed the steady-state limit; full session source acquisition is still required by FastF1, even though the LiveF1 collection is windowed. The existing archive downloader has its own byte limits/cache. Prepared display assets and prior revisions are retained rather than discarded with raw caches.

The localhost WebSocket delivers validated bundles dynamically. No frontend source edit, production rebuild, browser refresh or HTTP file server is needed for a new circuit. Preparation never stops/restarts the live source, changes TEST state or controls the animation clock. Disconnecting a browser does not cancel a backend job. Backend/CLI interruption leaves published geometry intact; retry reuses it and fills missing annotations. A process ownership lock prevents duplicate work for the same circuit; stale locks are reclaimed only when the owner is demonstrably gone. Unknown locks are not stolen.

## Windows setup

Run from the repository folder. Keep the two Python environments separate. These commands deliberately use explicit executables; activating an environment is optional.

```powershell
git fetch origin
git switch feat/automatic-circuit-preparation
git pull --ff-only origin feat/automatic-circuit-preparation

# Only create an environment if it does not already exist.
if (!(Test-Path .\.venv\Scripts\python.exe)) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r bridge/requirements.txt
.\.venv\Scripts\python.exe -m pip check

if (!(Test-Path .\.venv-fastf1\Scripts\python.exe)) { py -3.12 -m venv .venv-fastf1 }
.\.venv-fastf1\Scripts\python.exe -m pip install -r bridge/requirements-corners.txt
.\.venv-fastf1\Scripts\python.exe -m pip check
.\.venv-fastf1\Scripts\python.exe -c "import fastf1; print(fastf1.__version__)"

npm ci
```

Never install both requirements files into the same environment. The bridge does not import FastF1. If using a custom importer environment, set the path in the terminal starting the bridge/coordinator:

```powershell
$env:F1_FASTF1_PYTHON = (Resolve-Path .\.venv-fastf1\Scripts\python.exe).Path
```

An absent/broken importer environment produces an annotation warning, not a bridge startup failure. Previously prepared assets load without invoking either importer.

## Mexico through the dashboard

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --login --idle --allow-test --allow-prepare
```

Terminal 2:

```powershell
npm run dev
```

1. Open `http://localhost:5173` and the existing live-session page.
2. Expand Development diagnostics, set archive year **2026**, click **List sessions**.
3. Select the published **Mexico City Grand Prix · Race**. Selection performs asset lookup; it does not download a recording or change playback.
4. Expand **Circuit preparation**, click **Prepare / retry missing annotations**. First-time processing may take several minutes. Watch collection/geometry/corners/sectors stages. Missing or unpublished source data is a failure/warning, never a fabricated map.
5. Load a TEST clip from the same session. Try start offset **5400**, duration **480**, then Play at 1×. This is a starting window, not a guarantee of useful footage; use the existing window diagnostics or another offset if needed.
6. Geometry appears as soon as it is published; annotations update when available without refresh/restart. If you prepared a different session from the currently playing one, it must not replace the current session's display.
7. Inspect the outline's complete coverage and direction. Drivers should follow the path without being snapped. Compare all available corner anchors and physical sector locations against a reliable map. Default sector colouring uses calculated boundaries, not equal thirds. Imported records remain provisional.
8. Pause/resume/restart and change speed; preparation should not alter those behaviors. Test Austin afterward: its local assets, label size/spacing, source selections and animation should be unchanged.
9. Stop and restart the backend/frontend, reselect Mexico and load a clip. Cached assets should display without repeating preparation.

The toolbar's GPS compatibility status is independent of annotation confidence. At least **five fresh on-track driver positions** are required for the initial sample check. Recent positional p95 must be within **3% of geometry extent**; otherwise markers are withheld. This is a configurable-code conservative diagnostic, not an accuracy certificate. Missing/stale samples produce `waiting-for-gps`, shifted coordinates produce `incompatible`, and aligned samples produce `compatible-sample`. Cars are not projected onto the racing line to conceal errors. The same guard applies to dynamic TEST and LIVE circuits; Austin's existing behavior is unchanged.

If fewer than five drivers are available, the dynamic outline remains visible while driver markers wait. A single driver-only recording is therefore not sufficient for this initial check.

## CLI Mexico preparation and batch resume

Use this instead of the UI job, or after stopping other preparation jobs. The normal bridge may keep running for viewing; it receives updated assets on its next lookup (reselect the archive session or reconnect). UI-started jobs push updates as they progress.

```powershell
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Mexico --session Race --login
```

Only the explicitly requested season/session is used. Local LiveF1 login stays on the backend. If no unique matching archive session exists, the command stops instead of selecting another race. Existing complete assets are skipped; incomplete assets retain their geometry and retry missing annotations.

If all default windows lack complete laps, choose bounded alternatives without editing JSON:

```powershell
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Mexico --session Race --windows 4200 4800 6600 --retry-annotations
```

Prepare available race sessions serially:

```powershell
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --batch --login --retry-annotations
```

Rerun to resume. The process deduplicates circuit keys, skips complete assets, preserves Austin, continues after per-circuit failure, and records complete/incomplete/failed/existing-local-reference outcomes. Missing stable metadata is explicitly failed/unsupported, not assigned an invented circuit identity. It does not claim calendar-wide support merely because events were listed.

```powershell
Get-Content .\circuit-assets\batch.json
Get-ChildItem .\circuit-assets -Filter job.json -Recurse | ForEach-Object {
    Get-Content $_.FullName
}
```

`--store C:\path\to\circuit-assets` and backend `--circuit-store C:\path\to\circuit-assets` must agree if you use a custom writable location. Do not point this at `public/circuits` or an authentication cache.

## Preparation, validation and LIVE readiness

- **Geometry-ready:** usable geometry passed automatic closure/held-out/coverage checks; annotations may be absent.
- **Complete preparation:** geometry, corner import and sector calculation succeeded. This is not physical verification.
- **Provisional:** generated geometry/annotations have not been independently reviewed; precision and FIA warnings remain intact.
- **GPS compatible sample:** fresh incoming positions align with the stored native mapping. This is a sampled runtime check, not proof that an entire live weekend is validated.

Keep this PR draft until real Mexico data and local visuals have been reviewed. No DRS zones, pit lanes or official timing-line coordinates are invented. The runtime guard detects large translation/scale/layout disagreement; it does not solve recalibration automatically and can miss mismatches that happen to overlap the observed track sections. No hardware deployment or automatic race-weekend switching is added here.

## Checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s bridge/tests
.\.venv-fastf1\Scripts\python.exe -m unittest bridge.tests.test_corner_import bridge.tests.test_sector_import bridge.tests.test_boundary_audit bridge.tests.test_preparation_worker
npm test
npm run lint
npm run build
```

Coordinator tests use synthetic source samples and simulated acceptance metadata; they do not establish real-world Mexico accuracy. The separate worker test reads a cached synthetic source, imports through its actual dedicated interpreter, writes an annotation result, and confirms the calibration input is unchanged.

## Mexico geometry failures: structured diagnostic workflow

A generic `source unavailable or insufficient complete on-track laps` from the initial implementation did **not** establish that laps were insufficient. A blanket exception handler used that same message for retrieval, decoder, cache, schema and calibration exceptions. It is now replaced with stage-specific per-window results.

Preparation now requests only **SessionInfo, TimingData and Position.z** rather than downloading/decoding unrelated CarData and other feeds. Previously unrelated telemetry could consume the shared archive byte budget or abort geometry extraction. The normal LIVE/TEST downloader still defaults to its original full topic set and cache key. Partial geometry clips use a separate cache key. Extraction only applies timing deltas; unrelated messages cannot reset the timing seed or abort GPS collection. Samples in a compressed position batch are sorted by source UTC before deduplication. These are reproduced robustness defects, **not a claim that either caused the real Mexico failure**.

No cleaning/closure/gap/staleness/held-out thresholds were relaxed. Candidate lap groups, accepted complete laps and reasons are recorded separately. Incomplete-lap detail distinguishes too few samples, duration outside 40–240 seconds, GPS gaps over 2500 ms, invalid extent and insufficient closure. Those subreason counts can overlap for one rejected lap; other counts identify their sample-versus-lap units explicitly.

Each attempted window now reports:

- Stage, outcome and offset; whether archive retrieval succeeded or failed.
- Sample-cache and archive-cache use, partial archive event/byte counts and current topic where available.
- Event counts by topic, capability/parse failures and clock basis.
- Decoded/accepted GPS records, invalid timestamps, duplicate/older records and represented driver count.
- GPS-versus-stream clock-skew summary (no raw position/time records).
- Candidate/accepted lap counts, rejection counts and detailed incomplete-lap reasons.
- Whether calibration ran, held-out metrics, threshold and spatial coverage check when reached.
- Exception class, allowlisted error code, repository file/function/line and an actionable hint. Arbitrary exception messages, upstream responses, stack locals, credentials and URLs are **not** exported.

`null` means a stage was not reached or a count is unknown; it is not a measured zero. With a normalized sample-cache hit, original retrieval/extraction counts are reused, explicitly labelled cached. The extraction cache version changed so old sample caches are not mistaken for a new successful extraction. Prior files and prepared assets are not deleted. Topic-filtered requests may need to retrieve a new bounded archive clip once.

The report is saved after every attempt, including failures, at:

`circuit-assets/circuit-65-2026/geometry-diagnostics.json`

It is also retained in `job.json`, emitted as CLI progress JSON and shown in expandable per-window sections in the development Circuit preparation panel. Final failure does not erase the report. The report contains counts and safe failure metadata, not raw telemetry or authentication data, and is the appropriate file to share for further investigation.

After stopping the old backend, pull and rerun:

```powershell
git switch feat/automatic-circuit-preparation
git pull --ff-only origin feat/automatic-circuit-preparation

# Existing environment: no dependency changes required.
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Mexico --session Race --windows 5400 6000 3600 --login

$report = '.\circuit-assets\circuit-65-2026\geometry-diagnostics.json'
Get-Content $report -Raw
Copy-Item $report .\mexico-geometry-default-windows.json

# Optional: inspect alternative windows, preserving the first report above.
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Mexico --session Race --windows 4200 4800 6600 --login
Copy-Item $report .\mexico-geometry-alternative-windows.json

$diagnostics = Get-Content $report -Raw | ConvertFrom-Json
$diagnostics.windows | Select-Object offset,stage,status,archiveRetrieved,eventCount,decodedPositionRecords,driversRepresented,candidateLaps,acceptedCompleteLaps,calibrationAttempted,reason | Format-Table -AutoSize
$diagnostics.windows | ForEach-Object { $_.error | ConvertTo-Json -Depth 8 }
```

Do not delete Austin files, raw recordings or annotation caches to run this. If using a custom `--store`, use that directory for `$report` as well. Already complete assets are intentionally skipped by normal preparation; this procedure targets the observed Mexico case where no geometry exists.

For the UI retry, restart with the updated backend:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --login --idle --allow-test --allow-prepare
```

In another terminal run `npm run dev`, select the Mexico Race and click Prepare / retry. Expand each window's report. An archive authentication/download/schema exception should no longer be described as insufficient laps. If genuine cleaning rejection remains, inspect its counts before choosing another window or changing any algorithm.

Real Mexico data was not accessible in the implementation environment: the latest probe returned `authentication-required`. Real-data success remains unverified; synthetic decoder, extraction, rejection, error-safety and calibration regressions do not establish Mexico accuracy.

### All topics fail inside elapsed_ms

The supplied Mexico report shows all three streams failing in timestamp parsing before a single event is accepted. This excludes lap cleaning and calibration as the cause of that run. It does not establish whether the returned body contains an alternate timestamp format or non-stream content.

The reader now matches the actual timestamp prefix rather than slicing twelve characters. It accepts elapsed timestamps with supported variable fractional precision and separates the JSON payload at the matched boundary. Timestamp ranges are validated. HTML/markup, JSON lacking an elapsed prefix, quoted content without a prefix and other unsupported prefixes receive `invalid-stream-format`, not a misleading `no-events` conclusion. Nothing is reinterpreted as GPS or assigned a guessed clock.

Per-topic errors include `formatKind` and a 32-character structural mask `prefixShape`: letters become `A`, digits become `9`, and only selected punctuation is retained. No original text, account data or raw response body is exported. These fields distinguish an actual stream-prefix issue from a login/security/routing/error response returned in place of telemetry. HTML alone does not prove which of those caused it.

Pull the latest PR #6 update and repeat the existing Mexico command, then inspect `archiveTopicErrors` in `geometry-diagnostics.json`. Do not share raw stream responses or credentials. If parsing still fails, share the sanitized report; an `html-or-markup` or missing-prefix result requires addressing source delivery rather than choosing additional lap windows.

### Mexico's day-prefixed elapsed timestamp

The subsequent real diagnostic mask was `9.99:99:99.999` immediately followed by normal JSON/compressed JSON string payloads in all three topics. This identifies the unsupported **day-prefixed elapsed timestamp form** `d.hh:mm:ss.fff` (the masked day digit itself is unknown), rather than evidence of HTML or an authentication page. The parser now accepts both `hh:mm:ss.fff` and `d.hh:mm:ss.fff`, including supported fractional precision. Days are converted to elapsed milliseconds exactly; time is not rebased or guessed. Day-prefixed hours must be below 24; ordinary unprefixed elapsed hours may exceed 23.

Tests reproduce the reported shape for metadata, seeded timing and compressed-position payload framing at offset 5400, plus nonzero days and midnight rollover. First parsed source offsets per topic are now included as `archiveFirstOffsetSeconds`, so any genuine window/origin issue can be distinguished next. The full authenticated Mexico reconstruction still needs the local rerun; this fixes the demonstrated framing mismatch, not a claim that all subsequent geometry checks have passed.

No cache deletion or dependency changes are needed. Pull the update and repeat the one-window Mexico command above. If parsing succeeds, diagnostics should advance to extraction/cleaning/build with real counts instead of all topics reporting `invalid-stream-format`.

### Readable streams but no events inside the requested window

A subsequent Mexico report had all three topics `available`, no parse errors, first timing/GPS records near 616 seconds, and zero events inside 5400–5880. This proves the reader did not find records in that window, but first offsets alone do not establish whether the stream ended earlier or jumped to a later source time.

Coverage diagnostics now include `archiveLastOffsetSeconds`, `archiveFirstAfterWindowSeconds` and per-topic `archiveWindowCounts` (`before`, `inside`, `after`). The last offset is the last **examined** timestamp, not a claim of the full stream's end if the reader stopped at the first record beyond the window.

For a no-events failure only, preparation can schedule up to **two additional measured windows**:

- If a Position.z record was observed beyond the requested end, try the window beginning at that observed source second (floored so the record is included).
- If the Position.z stream ended before the requested start and the observed span is at least 480 seconds, try its final 480-second window.

Every discovered attempt is labelled `windowSource`, and its predecessor records `discoveredWindow` with the measured reason. No coordinates or timestamps are fabricated/rebased. Authentication, parsing, invalid geometry and other failures do not trigger guessed-window retries. Existing byte limits, 480-second clip bounds and geometry checks remain. Source offsets now support up to seven days to allow actual day-prefixed clocks; this does not authorize downloading seven days of data. The reader still stops at the window end or the download byte limit.

Pull and rerun the same one-window command. Preparation will use the observed coverage to attempt bounded alternatives automatically when supported. If it still fails, the same sanitized report now contains the coverage and any discovered attempts; no need to manually guess more offsets.

If geometry is prepared at a different source offset, use `provenance.preparationWindowSeconds` from the calibration or the accepted window's `offset` in this report when loading a historical TEST clip. The TEST offset input accepts day-prefixed source ranges as numeric seconds. Preparation does not automatically change or restart playback.

### GPS records decoded, but every sample is invalid

The next real Mexico report successfully retrieves offset 92876: 478 position messages, 40,370 decoded samples, 22 drivers and modest clock skew. All 40,370 fail the numeric/finite/nonzero-position gate before lap grouping; zero candidates therefore does not prove missing complete laps. The report alone does not distinguish zero coordinates, missing fields, nonnumeric values or nonfinite coordinates, and zero timing messages inside the window does not establish whether a valid timing seed existed.

Cleaning now reports mutually exclusive `invalidSampleReasons` (missing, boolean, nonnumeric, nonfinite, both X/Y zero), count-only `fieldTypes` for X/Y/time and `lapNumberAvailability` across **all** samples before filtering. These never include coordinate values, timestamps, strings or driver identities. All-invalid windows are labelled `no-valid-position-samples`, distinct from insufficient complete laps. No numeric coercion or GPS quality threshold has been changed without evidence.

The already cached sample file can be inspected **offline**, without authentication or repeating any download:

```powershell
git pull --ff-only origin feat/automatic-circuit-preparation
.\.venv\Scripts\python.exe -m bridge.calibrate inspect --samples .\circuit-assets\gps-cache\7d87504327050c365cbd3127e841f8fc489ac34f89eaf2597307752c7dd6401f.json.gz
```

That filename is the `sampleCacheEntry` in the supplied report. Use your configured store path if it differs. Share the count-only output. For a normal preparation rerun, the same counters are also included in geometry-diagnostics.json, using the sample cache when available. Real Mexico's invalid-value cause remains pending this inspection; do not assume the coordinates are zero or change timing/calibration to compensate.

### Confirmed zero-GPS/missing-lap Mexico window

The local inspection confirmed **all 40,370 records have integer X=0, Y=0, and no lap number**. This is real placeholder/unusable data in the selected window; the evidence does not prove whether later race data is usable or unavailable. Treating those samples as a circuit would fabricate geometry.

After an all-zero or missing-lap window, preparation now performs **one bounded source scan** within the same selected session. It first looks for positive lap numbers for at least three drivers in TimingData, then for timestamped, finite, nonzero on-track coordinates with observed movement for at least three of those drivers. It selects the actual observed source offset as a candidate. The ordinary 480-second collection and full geometry validation still have to succeed afterward; discovery is not verification.

The scan has the archive's shared 64 MiB source-byte cap, a 200,000-message cap and a 120-second processing deadline checked between records (an outstanding network read remains subject to its existing timeout). It does not store an entire session/season. Count-only scan progress/errors appear under `usableWindowScan`, with `timedDrivers`, `movingDrivers`, bytes and rejection counts. No actual driver positions are exported. If lap timing or moving GPS cannot be found within those limits, the scan reports that limitation rather than constructing an outline. At most two additional discovered windows are still permitted, and this usable-data scan runs at most once per preparation job.

Reuse the cached invalid window and let the new scan find a measured candidate:

```powershell
git pull --ff-only origin feat/automatic-circuit-preparation
.\.venv\Scripts\python.exe -m bridge.preparation --year 2026 --event Mexico --session Race --windows 92876 --login
Get-Content .\circuit-assets\circuit-65-2026\geometry-diagnostics.json -Raw
```

Do not delete the cached sample file or lower the zero-coordinate/lap requirements. A successful synthetic regression now reproduces the zero/missing-lap window followed by a later candidate and normal geometry build, but real Mexico discovery and final alignment remain locally unverified.
