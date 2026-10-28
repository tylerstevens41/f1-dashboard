# Circuit annotation workflow

The renderer uses the same calibrated geometry and animated driver components as PR #4. An annotation file stores fractions of the geometry path's arc length. `startFinish`, `sector1End` and `sector2End` identify three independent points; `direction` says whether racing follows increasing or decreasing geometry distance. The origin is never assumed to be the start line. Wrapped segments are split at the geometry origin. Invalid or missing sectors use a neutral centre line, never equal thirds. Annotations are keyed to circuit ID, layout version and a fingerprint of the projected geometry; changing your calibration invalidates old placements. A closed path is required for lap annotations. Fractions derived from racing-line distance are not automatically FIA surveyed centreline distances.

The 2026 FIA United States GP competition map (document 7, 22 October 2026) identifies Austin's 20 corners, intermediate S1 65 m before T7, S2 65 m before T13, and sector lengths S1 1.914 km, S2 1.941 km and S3 1.658 km, for a 5.513 km circuit. Source: https://www.fia.com/system/files/decision-document/2026_united_states_grand_prix_-_competition_notes_-_circuit_map_pit_lane_drawing_and_emergency_exits_map.pdf . These are event-specific reference values, not verified coordinates in your GPS calibration. No turns or sector positions have been committed as verified. Telemetry timing message receipt is not an exact crossing timestamp.

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

Keep your existing local calibration. From the repository:

```powershell
git switch feat/f1-circuit-annotations
git pull --ff-only origin feat/f1-circuit-annotations
.\.venv\Scripts\Activate.ps1
python -m pip install -r bridge/requirements.txt -r bridge/requirements-corners.txt
python -m bridge.corner_import --year 2026 --event "United States" --session R --circuit austin --layout austin-livef1-v1 --source-output data-cache/austin-fastf1-2026.json
python -m bridge.corner_import --source-input data-cache/austin-fastf1-2026.json --calibration public/circuits/austin-calibration.json --circuit austin --layout austin-livef1-v1 --output public/circuits/austin-corners.json
python -m bridge.server --login --idle --allow-test
```

Use a second terminal:

```powershell
npm ci
npm run dev
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
    python -m bridge.corner_import --year 2026 --event "United States" --session R --source-output data-cache/austin-fastf1-2026.json
} finally {
    Remove-Item Env:F1_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:F1_PASSWORD -ErrorAction SilentlyContinue
    Remove-Variable fastF1Credential -ErrorAction SilentlyContinue
}
```

Use this only with an account authorized to retrieve those archives. If authentication or the upstream feed remains unavailable, retain your current dashboard and report the importer error type; do not share credentials or token caches. The script never substitutes invented data.
