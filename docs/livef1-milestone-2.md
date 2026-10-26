# Milestone 2: measured LiveF1 GPS calibration

Branch: `feat/livef1-gps-calibration`. PR base: `feat/livef1-shared-ingestion` (PR #2), never `main`. PRs #1 and #2 remain prerequisites; nothing is merged automatically.

## Findings and scope

The existing live map **does not load the decorative `austin.svg`**. It draws 76 points from `austin-gps-reference.json`, whose session/date and calibration provenance are unknown. The decorative SVG is a different coordinate frame, including a parent translation. The reference's native bounds, the SVG's viewBox, and screen Y orientation cannot be compared directly without registration. SVG display preserves aspect ratio; normal car and outline coordinates are translated using the same bounds. Therefore an arbitrary independent CSS scale is not the right fix.

A reproducible geometric comparison of the committed SVG against the committed legacy reference (not new authenticated race data) found a uniform scale + reflection + approximately -21.6° rotation could fit that reference with p95 around 0.54% of its bounding diagonal; affine p95 around 0.49%. This means those two existing shapes are broadly compatible after registration. **It does not prove either matches the user's historical session, that the reference's start line is correct, or that a new real trajectory needs only that transform.** No old-reference-derived transform is installed as a verified calibration.

The previous animated marker restarted a three-second animation on every update and rejected jumps over a fixed 3000-unit distance. That could produce lag/stuck markers independent of geometry. Movement now uses timestamped samples and a short configurable buffer.

No authenticated GPS data is available to the agent. No calibration artifact or fabricated Austin trajectory is committed. Until the local workflow below runs, the legacy outline remains visibly **missing calibration**. A generated candidate can be previewed in LIVE and TEST immediately; it cannot claim verified status without held-out checks and local visual/start-line review.

## Workflow and schema

`bridge.calibrate collect` uses one bounded real LiveF1 clip, checks its circuit metadata, decodes **all** Position.z samples (including batches), and joins them with the same deep-merged TimingData used by the dashboard. It writes a backend-only samples file with source session IDs, driver IDs, source/frame timestamps, lap counters, GPS status and available InPit/PitOut flags. It neither requests credentials from the browser nor stores a season.

`build`:

1. Rejects non-finite/zero positions, samples over 5 seconds from their archive frame clock, off-track samples and records without lap counters.
2. Rejects entire laps with observed pit flags, fewer than 45 points, durations outside 40–240 seconds, gaps over 2.5 seconds, or endpoints farther apart than 6% of their native-coordinate bounding diagonal. A long outage is not bridged to manufacture a lap. Pit/off-track coverage depends on actual available topics.
3. Removes isolated spikes using neighboring step distances. These are empirical guards, not official speed or track-width limits.
4. Requires at least three complete laps; holds out every third lap before reconstruction. Resamples training laps by arc distance, adjusts small lap-boundary phase differences without reversing travel, and takes a median with light circular smoothing. The result is a representative racing trajectory, not a surveyed track centreline.
5. Samples the existing closed SVG path, including parent transforms. Tries rotation, translation, uniform scale and reflection with multi-start nearest-neighbor registration; then fits affine distortion for comparison. Both trajectory-to-outline and outline-to-trajectory errors are reported. Shape fitting does not establish official corner correspondence or start/finish.
6. Compares p95 error against a configurable threshold (default **1.5% of the native bounding diagonal**, not metres). Reports similarity sufficient / affine candidate / GPS rebuild recommended. The generated preview always uses the measured GPS candidate so car coordinates need no cross-feed assumption; the registered decorative SVG remains a comparison layer.

Output schema: `livef1-circuit-calibration-v1`, circuit ID, layout version, native geometry points/path, source-to-native affine matrix, start/finish inference, empty future annotation configuration, training/held-out IDs, error metrics, source provenance and candidate/verified status. The same artifact is consumed by LIVE and TEST. Native geometry is translated/flipped for display once; only car positions pass through the declared mapping. No nearest-track-point snapping is applied to cars.

The sample at path fraction zero comes from the timing lap-counter transition and remains **inferred/unverified**. Local review must check timing latency, lap closure and direction. Official corner/sector/DRS positions remain empty for the later editor milestone. Updating geometry/layout version requires rechecking annotation anchors.

`validate` excludes all training lap IDs, computes errors on eligible held-out/new laps, and can mark verified only after numeric checks pass plus both explicit local visual and start/finish confirmations. Synthetic unit datasets can never be verified. These flags record human review; they cannot replace doing that review. Verification applies to the tested coordinate frame/session/layout, not every future F1 weekend.

## Windows PowerShell: exact steps

Run from the repo root. If a branch already exists locally, use `git switch feat/livef1-gps-calibration` instead of `--track`.

```powershell
git fetch origin
git switch --track origin/feat/livef1-gps-calibration
.\.venv\Scripts\Activate.ps1
python -m pip install -r bridge/requirements.txt
python -m bridge.server --login --idle --allow-test
```

If `.venv` does not exist, run `py -m venv .venv` first. Login remains local through LiveF1; never share the token/password. Keep the backend running.

In a second terminal:

```powershell
npm ci
npm test
npm run dev
```

Open `http://localhost:5173`. Select Live Race → LIVE; expand **Development diagnostics** (closed by default). List 2026 sessions and select **United States (Austin) · Race**. Set Start offset **600**, Clip length **480**, Load TEST, then Play. Offset means elapsed seconds in the archive stream, **not** lights-out or a lap number. Adjust it based on your known working lap-3 window if 600 does not include sufficient running.

The panel shows selected session, clip clock/duration, state and valid GPS count. **Find on-track windows in loaded clip** ranks 15-second bins by on-track driver/sample coverage; clicking a result fills the start offset for the next load. It scans only the already-loaded bounded clip. A useful bin is not proof of complete calibration laps.

In a third activated Python terminal, collect and build while authentication is cached:

```powershell
.\.venv\Scripts\Activate.ps1
python -m bridge.calibrate collect --year 2026 --meeting Austin --session Race --circuit austin --start 600 --duration 480 --output data-cache/calibration/austin-training.json.gz
python -m bridge.calibrate build --samples data-cache/calibration/austin-training.json.gz --svg public/circuits/austin.svg --svg-path-id path4133 --layout-version austin-livef1-v1 --output public/circuits/austin-calibration.json
```

Use the actual historical year you successfully loaded if different. Each request retains the Milestone 1 600-second/64 MiB bounds. If the transfer guard trips, use an earlier/shorter window; if too few complete laps remain, collect another bounded window and pass both filenames to `build --samples file1 file2`. Do not increase bounds to a season download.

A previously captured real bridge clip can be used without another download:

```powershell
python -m bridge.calibrate collect --clip recordings/livef1-small.json.gz --circuit austin --output data-cache/calibration/austin-training.json.gz
```

A two-minute recording may not contain three complete laps; the build correctly refuses it in that case.

Return to the browser, click **GPS calibration overlay**, then **Reload calibration JSON** (or refresh). A candidate badge should appear. Toggle:

- calibrated GPS outline;
- raw/native GPS samples (orange);
- transformed accepted GPS samples (cyan);
- registered original SVG (purple);
- the unregistered original SVG (clearly labelled comparison, not a GPS-aligned layer);
- real driver markers.

The original SVG overlay preserves its aspect ratio. Raw sample layers are downsampled for drawing; numeric errors use complete eligible resampled laps. Live markers use buffered measured samples. Geometry registration and animation cannot hide systematic GPS drift by snapping.

Collect a separate validation window and compare it in TEST:

```powershell
python -m bridge.calibrate collect --year 2026 --meeting Austin --session Race --circuit austin --start 1080 --duration 480 --output data-cache/calibration/austin-validation.json.gz
python -m bridge.calibrate validate --samples data-cache/calibration/austin-validation.json.gz --calibration public/circuits/austin-calibration.json
```

Check the held-out p95/max error, rejected laps, and SVG comparison in the JSON/report. Watch multiple drivers and complete laps in the validation window. Check direction, the full lap including slow corners, pit-lane departures, label identity through position changes, and actual timing start/finish alignment. Small racing-line offsets are expected; systematic drift, reflected travel or a shortcut across a section is not acceptable. Large fit errors require investigating source/layout/window quality, not raising the threshold to conceal them.

Only after numeric and visual checks, and confirming the start/finish reference, record the local verification:

```powershell
python -m bridge.calibrate validate --samples data-cache/calibration/austin-validation.json.gz --calibration public/circuits/austin-calibration.json --confirm-visual --confirm-start-finish
```

Reload calibration JSON. If checks fail, it remains a candidate. Share the numeric report or commit the generated geometry after review if desired; credentials and backend clips must remain local. Calibration debug points include public sporting coordinates, never auth headers. Avoid committing backend cache files.

## Movement and layout

The backend retains 24 timestamped GPS samples per driver, including compressed-message batches. The renderer interpolates along the measured segment with a 250 ms buffer (scaled with TEST speed), compensates the buffer anchor for transport delay, and never extrapolates. A conservative native-units/time spike guard rejects isolated jumps; a gap begins a new segment. Missing samples may hold briefly, then hide after 2.5 seconds. Reacquisition reappears at a real sample instead of drawing a line across the outage. Thresholds live in circuit configuration; they are not Austin transforms hardcoded into JSX.

The timing tower sizes to the remaining application height. Its rows scale for 22 cars, its header is sticky, and its contents scroll independently when needed. Diagnostics and overlay controls are collapsed/off by default and have their own bounded scroll areas. The production build excludes development controls. Narrow layouts stack the tower/map with scrolling rather than clipping either. F1 fonts, team logos and colors remain unchanged. Visual fit at 1920×1080 and 1366×768 must still be checked locally.

## Checks and merge gate

Run:

```powershell
python -m unittest discover -s bridge/tests -v
npm test
npm run lint
npm run build
```

Tests cover registration with rotation/reflection/scale/translation, SVG group transforms, invalid/stale/pit filtering, incomplete data refusal, held-out separation, calibration persistence, synthetic verification rejection, source-native car mapping, interpolation/gaps/spikes/recovery, bounded sample history, renderer layers and all earlier ingestion tests.

No real Austin alignment, live subscription, start/finish accuracy, or browser layout result is claimed by automated tests. The environment lacks a Chromium executable, so browser visual QA remains local. Keep PR #3 draft until the real collection/build/held-out workflow and 20–22-car visual layout checks pass. Do not merge PRs #1/#2/#3 automatically.
