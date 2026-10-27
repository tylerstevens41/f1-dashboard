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
