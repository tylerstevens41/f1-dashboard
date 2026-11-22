# Production LIVE UI and tyre artwork

## Audit and scope

The PR #7 interface gated developer panels only on `/wall`, so the normal root
Live Race view exposed LIVE/TEST controls, telemetry counts, controller JSON,
calibration and annotation tools. `LiveRace` also linked two independent legacy
OpenF1 replay entry components. They were not used by the current LiveF1 TEST
pipeline. `AustinReplay.jsx` and `ReplayRace.jsx` are removed, along with their
only imports and buttons. Shared circuit/timing utilities and existing replay
source data/scripts remain untouched; this is not a repository-wide API migration.

The current tower drew a CSS circle with a letter. Exact existing artwork is
actually under `public/tyres/`, not `public/`. Each file declares width/height
100% and viewBox `0 0 500 500`; artwork is unchanged.

## Routes and authority

- `/`: normal Dashboard/Live Race navigation, no developer controls.
- `/wall` (or `?wall=1`): read-only wall view, automatic switching preserved.
- `/dev`: AUTO/MANUAL controls, manual LIVE discovery/start/stop, historical TEST,
  development diagnostics, preparation, GPS/animation diagnostics, appearance and
  annotation tools. Circuit tools work in a built Vite preview as well as dev.

These routes reuse one App-level feed and the existing backend controller.
Opening `/dev` is not needed for AUTO. Manual TEST still requires the backend
`--allow-test` flag. A selected TEST session is labelled historical in production;
it is never labelled LIVE. The routes are presentation separation, not a security
boundary: keep the existing local backend/network access restrictions.

GPS compatibility validation and marker gating remain active. Production shows a
short waiting/incompatible warning; detailed p95/rejection counters remain in dev.
Track/session status and the latest race-control messages remain visible.

## Tyres

Shared LIVE/TEST tower uses `race/TyreIcon.jsx` and `race/tyres.js`:
SOFT/S → tyres/soft.svg, MEDIUM/M → tyres/medium.svg, HARD/H → tyres/hard.svg,
INTERMEDIATE/I/INTER/INTERS → tyres/intermediate.svg, WET/W/FULL WET → tyres/wet.svg.
Case, spaces, underscores and hyphens are normalized. Numeric specifications
(e.g. C3) are deliberately not guessed. Unknown or failed images show an em dash.
URLs include Vite BASE_URL. Tyre age remains beside the icon. Icons preserve their
square aspect ratio and use the existing row layout.

## Windows startup

Stop the previous frontend/backend with Ctrl+C, then from the repository:

```powershell
git fetch origin
git switch feat/production-live-ui-cleanup
git pull --ff-only origin feat/production-live-ui-cleanup
npm ci
.\.venv\Scripts\python.exe -m bridge.server --auto --login
```

In another PowerShell window in the same repository:

```powershell
npm run dev
```

Open http://localhost:5173/ or http://localhost:5173/wall. For developer controls
open http://localhost:5173/dev. To test existing historical clips, restart backend:

```powershell
.\.venv\Scripts\python.exe -m bridge.server --manual --idle --allow-test --login
```

Use the existing `/dev` historical session selector and clip controls; existing
calibrations/circuit assets are neither regenerated nor overwritten. Confirm all
five tyre artworks, tyre ages and a stint change in your existing clip, then check
root and wall views have no controls and that `/dev` still exposes them.

## Verification limits

SSR tests exercise normal/wall/developer rendering with a shared simulated feed,
compound changes, unknowns, public files and base URLs. Full backend and frontend
regressions, lint and production build must pass. Chromium visual testing was
attempted but the host denied its process socket creation; no screenshots or real
authenticated LIVE visual verification are claimed. Verify 16:9 fit and real tyre
changes locally. No backend lifecycle, transport, calibration or animation code
is changed by this milestone.

## Timing tower refinement

Column order: POS → DRIVER → GAP → TYRE → INT → BEST LAP → LAST LAP.
GAP remains `TimingData.Lines[number].GapToLeader`. INT reads only
`TimingData.Lines[number].IntervalToPositionAhead.Value` (flattened by the
existing presentation adapter to `IntervalToPositionAhead_Value`). The installed
LiveF1 library also recognizes this field in its timing processing. Our existing
raw nested pipeline preserves it without numeric conversion, including lap-based
strings. No new subscription, provider, or leader-gap subtraction is involved.
The leader and missing/empty/malformed values show an em dash. Provider strings
such as `+1 LAP` are retained. LIVE and historical TEST use the same component;
interval updates and running order remain keyed by driver number.

Tyre age retains its existing source, suffix and missing-value handling, but now
inherits the primary row font size/family, uses weight 700 and tabular numerals,
and stays centered beside the unchanged SVG with a 3px gap. The tower/circuit
split remains unchanged. Seven fixed-layout percentage columns sum to 100%, cell
padding is reduced from 6px to 2px per side, and numeric values/headers align
right. Below a 440px tower width, primary row values including age use 10px;
normal rows remain 11px. Unusually long provider values wrap rather than widening
or clipping the table. Narrow screens may therefore have taller rows.

To verify locally, pull this same branch, restart Vite and use your existing
LIVE or TEST session. Confirm GAP and INT differ, the leader shows a dash, tyre
age is bold beside the SVG, and all seven columns fit your normal resolution.
Repeat at a narrower viewport and check long lap-based strings. Automated SSR
and CSS/layout-contract tests do not establish pixel-perfect browser fit or real
LIVE interval availability; those remain local checks.
