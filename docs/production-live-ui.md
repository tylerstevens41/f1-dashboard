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
