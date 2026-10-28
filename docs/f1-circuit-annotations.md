# Circuit annotation workflow

The renderer uses the same calibrated geometry and animated driver components as PR #4. An annotation file stores fractions of the geometry path's arc length. `startFinish`, `sector1End` and `sector2End` identify three independent points; `direction` says whether racing follows increasing or decreasing geometry distance. The origin is never assumed to be the start line. Wrapped segments are split at the geometry origin. Invalid or missing sectors use a neutral centre line, never equal thirds. Annotations are keyed to circuit ID, layout version and a fingerprint of the projected geometry; changing your calibration invalidates old placements. A closed path is required for lap annotations. Fractions derived from racing-line distance are not automatically FIA surveyed centreline distances.

The 2026 FIA United States GP competition map (document 7, 22 October 2026) identifies Austin's 20 corners, intermediate S1 65 m before T7, S2 65 m before T13, and sector lengths S1 1.658 km, S2 1.941 km and S3 1.914 km, for a 5.513 km circuit. Source: https://www.fia.com/system/files/decision-document/2026_united_states_grand_prix_-_competition_notes_-_circuit_map_pit_lane_drawing_and_emergency_exits_map.pdf . These are event-specific reference values, not verified coordinates in your GPS calibration. No turns or sector positions have been committed as verified. Telemetry timing message receipt is not an exact crossing timestamp.

In development, open **Track appearance** and **Annotation editor**, then enable **Preview provisional annotations**. Choose start/finish and click the real calibrated track; choose the correct direction by comparing known turns and car movement. The optional FIA distance button estimates both boundaries relative to that start and direction. The estimate assumes proportional geometry distance and is explicitly provisional: use the FIA map, real GPS and independent checks to place/correct S1 and S2. The path fraction and distance in the editor describe the local geometry, not necessarily metres. The 20 corner numbers can be placed individually with the turn selector; adjust offsets to avoid overlap. The editor never assigns verified status on placement. Record evidence in provenance before manually changing an annotation's status to verified. Export validates sector order, layout, geometry and status. Browser-local drafts and appearance settings are stored locally; changing appearance does not change GPS data.

Export JSON is compatible with the registry: after inspection copy it to `public/circuits/austin-annotations.json` and reload. This file contains only annotation data and the geometry fingerprint. Production only displays verified features; provisional previews are development-only. On any mismatch, the file is ignored. Keep per-event/layout files separate if rules change. The data model accepts detection points, zones, speed traps and a separately surveyed pit-lane SVG path, but this editor currently places corners, finish and sector boundaries only; create other features by editing a reviewed JSON file. No pit-lane path, DRS zone, speed trap, or verified Austin turn location is supplied. Race-control flags have a separate global border; local flag locations are not inferred.

## Windows local check

From your repository, preserve your existing ignored `public/circuits/austin-calibration.json` and any local work. Then:

```powershell
git status
git fetch origin
git switch feat/f1-circuit-annotations
git pull --ff-only origin feat/f1-circuit-annotations
.\.venv\Scripts\Activate.ps1
python -m bridge.server --login --idle --allow-test
```

Open another PowerShell window in the repository:

```powershell
npm ci
npm run dev
```

Open the local Vite URL, enter the live tracker, select TEST, select the 2026 Austin Race, set start offset to approximately 5600 seconds and a short clip length, load and play. The existing calibration is loaded from `public/circuits/austin-calibration.json`; use **GPS calibration overlay → Reload calibration JSON** if needed. Confirm cars still follow the calibrated outline at 1× and other speeds. Expand **Track appearance** and enable provisional preview; expand **Annotation editor**, place finish and boundaries and inspect the colours. Export the JSON using the editor. Check lap direction, wraparound, S1 before T7 and S2 before T13 against the FIA map before recording verification. The calibration and annotation files contain no credentials by design, but inspect them before committing and exclude any recordings, caches and tokens. Do not commit them until you have checked that they contain only intended geometry/configuration and validation metadata.

The Python bridge receives `TrackStatus` and `RaceControlMessages` as topic data; global track status can feed the existing flag border later. A local/sector effect requires an explicitly reliable location mapping and has not been implemented.

## Automatic FastF1 corner import (PR #5 enhancement)

FastF1 3.9.0's `Session.get_circuit_info()`/`CircuitInfo` documentation describes X/Y map coordinates, number plus optional letter, visual label-offset angle, telemetry-derived distance and a display rotation. It warns that MultiViewer's manually created markers are not highly accurate. Documentation: https://docs.fastf1.dev/circuit_info.html ; API source: https://github.com/theOehrly/Fast-F1/blob/main/fastf1/mvapi/data.py . The implementation was checked against the installed 3.9.0 method/docstring and upstream source. `Distance` is itself computed by FastF1 from nearest reference-lap telemetry, so it is preserved as source metadata, not treated as an independent surveyed alignment or an official finish reference. Neither marshal sectors nor the first corner defines the three timing sectors.

The development importer uses `fastf1.get_session(year,event,session)`, loads one selected session with telemetry, calls `session.get_circuit_info()` and saves only normalized corner data and a reference lap. A dedicated ignored `data-cache/fastf1` cache is pruned toward 512 MiB between imports; active locked files are skipped and a fetch may temporarily exceed that size. It does not load an entire season. The dashboard makes no FastF1 network calls.

Alignment uses equal arc-length samples of a full FastF1 reference lap and the existing closed LiveF1 calibrated path. It searches cyclic phase and driving direction, and fits translation plus a uniform-scale orthogonal transform (including handedness). Alternating samples are held out from the fit; the result is rejected if RMS exceeds 1.5% of target extent, p95 exceeds 3%, or a distant competing fit is nearly as good. Each transformed corner is then projected onto path segments with distance, nonlocal ambiguity and corner-order checks. This is not unqualified nearest-point matching. Source rotation is retained, not blindly applied. FastF1 angle vectors are transformed by the fitted matrix and then the SVG Y reversal; cosmetic offsets prefer clearance from the track and attempt to separate labels. Corners remain provisional after passing these checks: numerical fit quality does not establish real-world correctness.

The importer never changes calibration coordinates or the LiveF1 mapping. It does not generate a new outline, finish, sectors, DRS or pit lane. Failure creates no guessed corner positions. If shape matching fails, inspect the source/target layout and reference lap; do not bypass thresholds or assume a rotation-only fix. Independent matched control-point tooling remains a future improvement for rejected fits.

### PowerShell: import once, load automatically

Keep your existing `.venv` and `public/circuits/austin-calibration.json`. LiveF1 1.3.0 and FastF1 3.9.0 require incompatible pandas versions: **never install their requirements together**. Use Python 3.12 for these commands. Activation is per terminal; explicit executable paths below also prevent accidentally using the wrong environment.

Pull this branch first:

```powershell
git switch feat/f1-circuit-annotations
git pull --ff-only origin feat/f1-circuit-annotations
```

Terminal 1: existing LiveF1 environment (create only if absent). Do not recreate or delete your working environment or change its pandas version:

```powershell
if (!(Test-Path .\.venv\Scripts\python.exe)) { py -3.12 -m venv .venv }
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r bridge/requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m bridge.server --login --idle --allow-test
```

Terminal 2: separate offline importer. Its only project imports are standard library and NumPy; FastF1 is imported lazily for fetching. It does not import LiveF1, `bridge.calibrate`, SVG tooling, or the backend. The calibration is read as JSON, never executed or overwritten.

```powershell
if (!(Test-Path .\.venv-fastf1\Scripts\python.exe)) { py -3.12 -m venv .venv-fastf1 }
.\.venv-fastf1\Scripts\Activate.ps1
.\.venv-fastf1\Scripts\python.exe -m pip install -r bridge/requirements-corners.txt
.\.venv-fastf1\Scripts\python.exe -m pip check
.\.venv-fastf1\Scripts\python.exe -c "import fastf1; print(fastf1.__version__)"
.\.venv-fastf1\Scripts\python.exe -m bridge.corner_import --year 2026 --event "United States" --session R --circuit austin --layout austin-livef1-v1 --source-output data-cache/austin-fastf1-2026.json
.\.venv-fastf1\Scripts\python.exe -m bridge.corner_import --source-input data-cache/austin-fastf1-2026.json --calibration public/circuits/austin-calibration.json --circuit austin --layout austin-livef1-v1 --output public/circuits/austin-corners.json
```

If a suitable cached `data-cache/austin-fastf1-2026.json` already exists, skip fetching and run only the second importer command. Otherwise the first command must succeed before alignment. The generated JSON is the only interface between importer and frontend: Vite and the LiveF1 bridge need neither FastF1 nor the importer environment running.

Terminal 3 (no Python environment needed):

```powershell
npm ci
npm run dev
```

For checks in the correct environments:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s bridge/tests
.\.venv-fastf1\Scripts\python.exe -m unittest bridge.tests.test_corner_import
npm test
npm run lint
npm run build
```

The importer refuses to overwrite an existing output. For another attempt, use a new output name, inspect it, then replace only the reviewed `austin-corners.json`; never remove the calibration. Failed fetches require checking data access locally. Our 2026 Austin attempt obtained session metadata but no timing/car/position telemetry without authentication, so no 20-corner export or local Austin alignment was verified here. Your LiveF1 login is not automatically FastF1's login. FastF1 3.9.0 can use backend-only `F1_USERNAME`/`F1_PASSWORD`; if needed, set these only in the importer terminal using `Get-Credential` and remove them immediately afterward. Never add credentials to React, JSON, commands in shared logs, or Git. No alternate paid service or silent prior-season fallback is used. An explicitly chosen accessible historical session is allowed but must be labelled with that actual season and verified against the intended layout.

Open the same 2026 Austin TEST clip around offset 5600. The dashboard automatically loads `austin-corners.json` and displays all aligned imported corners, including letter suffixes, as circular labels. Imported corners are visibly identified as provisional in diagnostics; this automatic display does not mark them verified. If the page was already open, use **Reload annotation files** in the editor area. Existing manual sector/finish JSON remains separate in `austin-annotations.json`. An incompatible circuit/layout/geometry file is rejected with a visible error.

Select Corner and a number/letter in the editor to move its anchor, edit offset or hide its label. Click placement now enables provisional preview immediately and shows a yellow selected-anchor ring; errors appear rather than silently returning. Changing offsets and re-exporting preserves immutable original source records in `importSource` and per-corner `source`, while manual edits override imported defaults by number+letter. A hidden label is retained as an override rather than deleted and re-imported on reload. Clear annotations hides imported defaults locally. Use Export JSON to publish reviewed overrides to `austin-annotations.json`. The import file remains the source of defaults. Small overlaps can still require label-offset adjustments; no claim of automatic layout perfection is made.

Validate Turns 1–20 against the FIA map, compare anchor error and whole-lap RMS/p95 in diagnostics, and check drivers still follow the unchanged calibration at 1×/2×/5×/10×. Authentication, real Austin registration and browser visual placement remain local verification steps.

If FastF1 requires authentication, the optional local-only importer invocation can use a masked prompt (no credentials are requested by this assistant):

```powershell
$fastF1Credential = Get-Credential
try {
    $env:F1_USERNAME = $fastF1Credential.UserName
    $env:F1_PASSWORD = $fastF1Credential.GetNetworkCredential().Password
    .\.venv-fastf1\Scripts\python.exe -m bridge.corner_import --year 2026 --event "United States" --session R --source-output data-cache/austin-fastf1-2026.json
} finally {
    Remove-Item Env:F1_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:F1_PASSWORD -ErrorAction SilentlyContinue
    Remove-Variable fastF1Credential -ErrorAction SilentlyContinue
}
```

Use this only with an account authorized to retrieve those archives. If authentication or the upstream feed remains unavailable, retain your current dashboard and report the importer error type; do not share credentials or token caches. The script never substitutes invented data.

## Timing/GPS start-finish and sector calculation

Run `bridge.sector_import` in `.venv-fastf1` to generate **all three** boundaries together. It reuses the corner importer's FastF1 cache, full-lap registration, geometry fingerprint, and ambiguity gates. It never changes LiveF1 calibration or your corner JSON. The optional `bridge.corner_import --with-sectors` flag can also create corners and all boundaries in one new output; existing corner-only caches must be refreshed to include multi-lap timing/position records. Neither command silently substitutes another season.

FastF1 3.9.0's `Telemetry` docstring and `Session._load_telemetry` source distinguish `SessionTime` (session elapsed time), `Date` (sample timestamp), and `Time` (can be slice-relative). Lap `LapStartTime` and lap-ending `Time` are session times. The collector uses the full original driver position stream, not merged car/position telemetry, and validates `Date - session.t0_date == SessionTime` and `LapStartDate - t0_date == LapStartTime` within 2 ms. This checks time-base consistency, not independent proof that feed clocks have zero systematic bias. Original `Source=pos` and `Status=OnTrack` samples are required.

Each lap must be accurate, completed, non-pit, non-generated, non-deleted and green/yellow. Sector durations must sum to LapTime within 3 ms; end-start must agree within 50 ms. Crossings use start, start+S1, start+S1+S2, and measured lap end. Each position is linearly interpolated between surrounding original GPS timestamps, with a maximum 500 ms bracket. Gaps over 750 ms away from crossings are counted rather than rejecting the lap; a crossing bracket over 500 ms is still rejected. Missing dates, invalid coordinates and extreme spikes remain rejected. Parsed/corrected sector SessionTimes are recorded as offset diagnostics and are not assumed to be exact crossing timestamps. The first 40 eligible laps are collected in lap-number/driver order, sampling multiple drivers when available.

The shared registration transforms crossings into the existing LiveF1 native geometry, then the path projection checks distance and competing nearby branches. Start and end estimates must agree within 0.5% of a lap; they form one circular estimate per lap. At least five distinct valid laps are required. Circular medoid/unwrapping, median and MAD-based rejection prevent estimates across path fraction 1/0 from averaging toward 0.5. P95 residual spread over 0.5% of a lap causes failure. Results retain fractions, accepted/outlier counts, native-distance spread, driver count, rejected-lap reasons, per-lap start/end estimates, GPS bracket durations, projection errors, registration RMS/p95, season and session.

The aggregate must follow the registered driving direction with three nontrivial unequal segments. Austin 2026 receives coarse checks against the FIA lengths, S1 before T7, S2 before T13, and the finish lying between T20/T1. Comparing geometry ratios scaled to 5513 m is only a screening check: GPS racing-line distances and FastF1's approximate corner markers are not surveyed FIA centreline distances. Differences over 10% for sector length or 100 m for the stated intermediate-to-corner distance raise discrepancy warnings; they do not alter estimates or establish verification. The calculated lap control/finish line may differ from the physical grid start line. All outputs remain **provisional**, even if coarse map checks pass. Tight visual/map checks and representative authenticated trajectories are still required.

### Windows: calculate Austin without replacing corners or reviewed edits

```powershell
git switch feat/f1-circuit-annotations
git pull --ff-only origin feat/f1-circuit-annotations
.\.venv-fastf1\Scripts\Activate.ps1
.\.venv-fastf1\Scripts\python.exe -m pip install -r bridge/requirements-corners.txt
.\.venv-fastf1\Scripts\python.exe -m bridge.sector_import --year 2026 --event "United States" --session R --source-output data-cache/austin-fastf1-boundaries-2026.json
.\.venv-fastf1\Scripts\python.exe -m bridge.sector_import --source-input data-cache/austin-fastf1-boundaries-2026.json --calibration public/circuits/austin-calibration.json --output public/circuits/austin-sectors.json
```

If a suitable multi-lap source JSON already exists, skip the fetch command. FastF1 will reuse its raw cache when fetching the session. Use the backend-only authentication workflow above if needed, changing the module to `bridge.sector_import` and the source-output filename. Never share credentials or token caches. Both source and output writers refuse existing paths: choose a new filename for a repeat calculation, review it, and explicitly replace the sector file only if wanted. Do not delete the calibration, corners, or manual annotation file.

Start the existing bridge in a separate terminal:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --login --idle --allow-test
```

Start the frontend in another terminal:

```powershell
npm run dev
```

Load the same Austin TEST race around offset 5600. The dashboard loads `austin-sectors.json` automatically; use **Reload annotation files** if already open. Calculated provisional boundaries display automatically as magenta/yellow/cyan segments plus the perpendicular finish marker. Existing non-null manual/reviewed boundary positions take precedence; they are not overwritten. Diagnostics and the editor show the original calculated fraction, spread and any override. To use a calculated position instead of an existing reviewed position, export/back up the reviewed annotations and click **Use calculated position (replace this override)** for that selected boundary. This explicit action preserves the prior position in `previousOverride`; it does not erase your whole file. Manual changes preserve `sourceEstimate` and set `manualOverride`; explicit deletion is also preserved. The finish origin is independent of the arbitrary first geometry point. No boundary ever defaults to an equal third.

The 1.65× corner label size is unchanged. **Corner label spacing** defaults to 1.15× and multiplies each existing offset vector only at render time, including manually adjusted vectors; it never rewrites stored offsets or anchors. Viewport padding accounts for the larger spacing; connector lines remain absent.

Validate start/finish against the map's timing control line; confirm direction and S1 approximately 65 m before T7 / S2 approximately 65 m before T13. Inspect the source-calculation panel, per-boundary spread, original versus manual fractions, rejected reasons and FIA discrepancy warnings in the exported diagnostics. A numerically coherent result can still have systematic telemetry timing bias; do not mark it verified solely because it renders cleanly. No real Austin boundary calculation has been verified by the implementer without the local authenticated source and calibration.

## Incorrect sector investigation and correction workflow

The supplied screenshot and actual 38-lap diagnostics are different evidence layers. Their median fractions are finish 0.9962572733, S1 0.2971121774 and S2 0.7088777190; these are observations, **not certified correct positions**. The registration residuals (RMS 24.19, p95 40.36 native units, extent 20924) and tight inter-lap clusters show precision. They do not establish physical timing accuracy.

A confirmed reference bug was found by rendering page 2 of FIA document 7 and extracting text with layout preserved: **S1=1658 m, S2=1941 m, S3=1914 m**. Prior code and documentation had S1/S3 reversed. The corrected source is `config/circuit-references/austin-2026.json`, with URL, page and version. For the reported observations, S1's 1658.61 m equivalent now matches the actual S1 length; S2/S3 remain discrepant. The 10% threshold is unchanged. A 330 m discrepancy must not simply be dismissed as racing-line variation. The map also says intermediates are 65 m before T7/T13; it provides no georeferenced LiveF1 line endpoints. Those corner checks use approximate FastF1 map markers, not surveyed coordinates. The audit now compares the **saved corner file** against corners independently reprojected from the sector source: this can expose a different set of anchors being used for validation and display.

A second confirmed code issue was that source-calculation diagnostics could be shown beside different effective boundaries retained from a manual file or browser draft. Whether that accounts for this screenshot requires the local/browser audit; it is not proven by the screenshot alone. The development **Boundary accuracy and display audit** now lists calculated fraction, displayed fraction, and winner/origin for each boundary. **Preview calculated boundaries only** temporarily ignores overrides without saving anything. **Show actual corner anchors and calculated crossings** draws small development-only anchor markers so circular-label offsets cannot be mistaken for timing locations. Normal labels and offsets are unchanged. **Use calculated position** remains an explicit choice and retains the previous override. New explicit SVG subpaths begin/end at the same cumulative-distance points as the markers, removing any dependency on dash phase for sector transitions. Python-to-JavaScript tests cover nonuniform point spacing, the reported 0.996/0.297/0.709 inputs and wraparound.

### Timing findings

FastF1's pinned 3.9.0 implementation was inspected: `_api._laps_data_driver` initially records sector update SessionTimes and then applies lowest-latency lap/sector corrections. `_api._align_laps` can align drivers from reported gaps. Therefore Sector1SessionTime/Sector2SessionTime are **parsed and possibly corrected values**, not necessarily untouched receipt timestamps or independently exact GPS crossings. `LapStartTime`/lap-end `Time` use processed lap timing; LapStartDate and position SessionTime are related through `t0_date`. Date/session equality is a time-base identity, not proof that the timing and position feeds have zero systematic bias. Duration-based crossings remain the primary estimates; no arbitrary time correction was introduced. Existing cached `timingReceiptOffsets` are accepted as legacy diagnostic fields; new collections name them `sectorSessionOffsets`. The shareable audit reports aggregate offsets but does not turn them into corrections.

### Revalidate using existing normalized cache — no download

```powershell
git switch feat/f1-circuit-annotations
git pull --ff-only origin feat/f1-circuit-annotations
.\.venv-fastf1\Scripts\Activate.ps1
python -m bridge.sector_import --source-input data-cache/austin-fastf1-boundaries-2026.json --calibration public/circuits/austin-calibration.json --corner-annotations public/circuits/austin-corners.json --output public/circuits/austin-sectors-candidate.json
python -m bridge.boundary_audit --calibration public/circuits/austin-calibration.json --corners public/circuits/austin-corners.json --sectors public/circuits/austin-sectors.json --source data-cache/austin-fastf1-boundaries-2026.json --output data-cache/austin-boundary-audit.json
```

If a manual annotation file exists, append `--annotations public/circuits/austin-annotations.json` to the audit command. Outputs must be new paths. Neither command overwrites calibration, corners, sectors or reviewed files. The audit exports only selected geometry/annotation numbers and aggregate timing statistics, not tokens, accounts, raw UTC or recordings. It compares old/new FIA validation, stored fractions, saved corner anchors and source-reprojected anchors. Precision and accuracy are distinct report fields.

Start the existing bridge and Vite as above. In **Boundary accuracy and display audit**:

1. Compare calculated and displayed fractions before changing anything.
2. Toggle calculation-only preview and actual anchor markers.
3. Use **Load candidate sector JSON (memory only)** to inspect `austin-sectors-candidate.json` without replacing any file. This preview is not persisted.
4. Export **safe browser boundary audit**. It includes active fractions and actual SVG subpath endpoint coordinates measured by the browser, but no raw GPS stream.

Compare browser output with Python's independently computed points:

```powershell
python -m bridge.boundary_audit --calibration public/circuits/austin-calibration.json --corners public/circuits/austin-corners.json --sectors public/circuits/austin-sectors-candidate.json --source data-cache/austin-fastf1-boundaries-2026.json --browser-audit "$env:USERPROFILE\Downloads\f1-boundary-browser-audit.json" --output data-cache/austin-boundary-comparison.json
```

Share the two audit JSONs if needed; they omit credentials, source samples and account data. Check which fraction is really rendered, source-versus-saved corner differences, and rendered endpoint errors. If calculation-only preview is right, deliberately adopt the calculated positions via the editor, or install the reviewed candidate as the defaults. Preserve backups and manual annotations. If preview remains wrong, do not drag until it looks plausible or claim the warning is solved: investigate the independent physical reference and feed synchronization.

### Recover laps rejected only for remote GPS gaps

The old normalized cache retains only accepted laps. It cannot recover the 959 discarded laps because their samples were not exported. The new collector permits gaps away from crossings, records their count/max duration, and retains the original strict 500 ms crossing bracket, finite-coordinate/date checks and spike veto. A missing chunk far from every crossing no longer invalidates otherwise sound estimates. Tests show a remote 3-second gap can pass while a 2-second gap at S1 still fails.

If desired, re-read the existing FastF1 raw cache in the library's offline mode, without requiring another session download:

```powershell
python -m bridge.sector_import --year 2026 --event "United States" --session R --cache data-cache/fastf1 --cache-only --source-output data-cache/austin-fastf1-boundaries-local-quality.json
python -m bridge.sector_import --source-input data-cache/austin-fastf1-boundaries-local-quality.json --calibration public/circuits/austin-calibration.json --output public/circuits/austin-sectors-local-quality-candidate.json
```

If the raw cache is incomplete, offline mode fails rather than silently fetching missing data. Your existing 38-lap normalized cache remains usable for auditing/recalculation.

### Optional independent physical timing-line reference

When reliable native coordinates can be established from an independently registered official map or surveyed timing-line data, the generic importer supports `--physical-reference`. There are **no invented Austin coordinates** supplied. The JSON schema `circuit-physical-timing-lines-v1` requires matching circuit, layout, geometry fingerprint, season, source/version provenance, and `lines` for `startFinish`, `sector1End`, `sector2End`. Each line must have two native coordinate endpoints `a: [x,y]`, `b: [x,y]` and positive `uncertaintyNative` for its registration. Register the official source independently; do not derive those endpoints by moving our current timing estimate or guessing from sector-length ratios.

The algorithm intersects each physical timing line with the calibrated path, requires exactly one unambiguous intersection and correct driving order, and retains the original timing estimate for comparison. Use:

```powershell
python -m bridge.sector_import --source-input data-cache/austin-fastf1-boundaries-2026.json --calibration public/circuits/austin-calibration.json --physical-reference data-cache/austin-physical-lines-reviewed.json --output public/circuits/austin-sectors-physical-candidate.json
```

This is an explicit reference-based alternative, not a time-offset fit. Outputs still remain provisional: a user-supplied reference does not automatically prove its own registration. `bridge.boundary_audit` accepts the same option for independent error measurement without changing annotations. Real Austin accuracy remains unverified until the local files/browser chain and reliable physical line evidence agree.
