# Milestone 1: one LiveF1 LIVE/TEST ingestion pipeline

## Status and evidence

Implemented on a branch stacked on PR #1. **Authenticated archive access and Austin calibration are not verified.** In this environment, the actual `https://livetiming.formula1.com/static/2024/Index.json` request returned HTTP 401. No credentials were requested from the user, supplied to the agent or added to source control. No synthetic race recording is shipped. Unit fixtures are explicitly synthetic protocol cases, not positioning evidence.

Installed and inspected **LiveF1 1.3.0**. This milestone pins that version because it has a transport seam that may change. Verified installed signatures: `RealF1Client(topics, log_file_name=None, log_file_mode='w')`, `_dispatch(self, frame)`, and `Session.get_data(self, dataNames, level='bronze', parallel=False, force=False)`.

Relevant upstream source:

- https://github.com/GoktugOcal/LiveF1/blob/main/livef1/adapters/realtime_client.py
- https://github.com/GoktugOcal/LiveF1/blob/main/livef1/data_processing/etl.py
- https://github.com/GoktugOcal/LiveF1/blob/main/livef1/data_processing/parse_functions.py
- https://github.com/GoktugOcal/LiveF1/blob/main/livef1/adapters/livetimingf1_adapter.py
- https://livef1.goktugocal.com/user_guide/historical_data.html
- https://livef1.goktugocal.com/user_guide/data_sources.html

`Session.get_data` supports static historical topics, but loads entire topic archives. Our bounded reader discovers the same session `Index.json` feeds, uses LiveF1's backend `auth_header()`, reads `.jsonStream` records incrementally and uses the installed LiveF1 compressed decoders. It stops at the clip end rather than loading a season or a full session into a DataFrame. A later start still requires reading and merging earlier sparse messages; a 64 MiB transfer limit can reject late windows. Choose an earlier window or a bounded recording in that case.

## Verified topic contracts (source inspection and parser tests)

| Topic | Transport shape and handling |
|---|---|
| `Position.z` | Compressed `Position[]`, each containing `Timestamp` and per-driver `Entries`; installed decoder produces `Utc`, `DriverNo`, `X/Y/Z`, `Status`. Latest valid sample/car retained; older samples ignored. |
| `CarData.z` | Compressed `Entries[]` with `Utc` and `Cars[number].Channels`; installed decoder maps channels to named telemetry fields. |
| `DriverList` | Raw driver-number-keyed dictionary. Preserve the dictionary key even when a delta omits `RacingNumber`. |
| `TimingData` | Raw `Lines[number]`, including nested times/sectors and sparse updates. |
| `TimingAppData` | Raw `Lines[number].Stints` and index deltas. **Installed `function_map['TimingAppData']` is `None`**; the old standard callback cannot parse this topic. The bridge preserves its raw dictionaries instead. |
| `TrackStatus` | Raw `Status`/`Message` with archive/live topic timestamps; retained without guessing a sector. |
| `RaceControlMessages` | `Messages` list or index dictionary; merge by index and retain the latest 100. Text displayed globally; sector coloring deferred. |
| `SessionInfo` | Raw `Key`, `Path`, `Meeting.Circuit.ShortName`, names and dates. Key/path transition clears previous session data. |
| `SessionStatus`, `SessionData` | Preserve raw status/session series; no automatic wall-mode switching in this milestone. |

Archive availability is discovered per session; topic names alone do not guarantee entitlement or publication. Missing streams/404 topics are reported. Only identity/session metadata may fall back to keyframes; final timing, tyres, positions and flags are never used as historical starting snapshots.

## Architecture

LIVE `DashboardClient` (RealF1Client transport) or TEST archive/recording → same `RaceState.ingest` → versioned local WebSocket → `useRaceFeed` / reducer → existing `LiveSession` timing UI and `LiveCircuitSvg` / shared renderer.

RealF1Client's `_dispatch` and `_stream` are subclassed for raw topic handling and connection diagnostics. No upstream monkey patch or global parser mutation. Authentication and transport reconnects remain in LiveF1. The compatibility seam is pinned/tested and needs re-verification before upgrading the library.

- Initial subscription snapshots reset the authoritative state; sparse deltas deep-merge indexed arrays/dictionaries, honor deletion markers and retain null clears.
- Browser reconnect receives a full snapshot. Generation/sequence numbers reject old updates; session transitions discard old drivers and timing.
- Each normalized topic message carries authoritative state for that topic. Driver identity/timing are retained when GPS is absent.
- TEST has an archive clock; pausing stops that clock. Stale GPS uses that clock, not today's wall time. LIVE uses wall time, so feed outages expire markers.
- TEST controls are opt-in on the loopback backend and shown only in Vite development. The frontend never sends credentials or arbitrary URLs. The bridge accepts only the F1 static archive host/path, limits WebSocket message size, and sanitizes errors.
- Diagnostics distinguish WebSocket connectivity from LiveF1 upstream connectivity and show source mode, session, circuit, GPS count/freshness, timing/race-control freshness and unverified calibration.
- Austin is selected only from explicit circuit metadata; unknown circuits show timing and an unsupported-map notice. Calendar registry expansion is Milestone 4.

## Bounds and fallback

Default clip: 120 seconds; maximum: 600 seconds. Network budget: 64 MiB/topic-window request set (index requests additionally limited to small JSON). Local cache: at most three clips and 128 MiB compressed; serialized/decompressed clip limit 64 MiB. No seasons are cached. Cache is ignored by git.

If archives are restricted, `--record` captures up to 120 seconds / 32 MiB / 30,000 events of **real incoming LiveF1 messages**. Stop with Ctrl+C to persist the clip. `--recording` plays that local file through the same pipeline, visibly labelled TEST. No demo race is substituted if the archive or recording is missing. Recordings remain backend-only and are not imported into React's `public/` directory.

## Windows verification

From the repo root, use two terminals. Python 3.12+ and Node 24 are recommended.

```powershell
git fetch origin
git switch --track origin/feat/livef1-shared-ingestion
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r bridge/requirements.txt
python -m unittest discover -s bridge/tests -v
python -m bridge.server --login --idle --allow-test
```

LiveF1 handles your local sign-in/token cache. Never put credentials into a `VITE_*` variable, browser field, git commit, issue or PR. Upstream may save its prompted credentials in the ignored local `.env` and token under the user's private LiveF1 directory. Both remain backend-only. Existing token caches are reused.

Second terminal:

```powershell
npm ci
npm test
npm run build
npm run lint
npm run dev
```

1. Open `http://localhost:5173`, select **Live Race → LIVE**, then expand **Development diagnostics**.
2. List **2024** sessions, select the **United States / Austin Race** (the UI includes meeting location), start offset **600**, clip length **120**, and load TEST. These are archive-stream offsets, not an assumed lights-out time. Select another window if no cars are on track there.
3. Play/pause/change speed. Confirm TEST label, session name, topic availability, driver identities, timing and tyres. The same tower/map is used in LIVE and TEST. Missing topics must remain missing, not show made-up values.
4. Austin mapping is only a candidate reference. Do not sign off coordinate accuracy until Milestone 2 compares real archive positions to it.
5. Reload the page mid-playback. Confirm a snapshot restores state without duplicate drivers. Stop/restart the bridge and verify WebSocket reconnect. Stop GPS updates and check expiry. Select another session and confirm no previous drivers/tyres remain.
6. Return to LIVE only when you want a live subscription. In production use `python -m bridge.server` without `--allow-test`. The old `python livef1-test/live_bridge.py` entry point still launches this backend.

Safe, payload-free capability report after local login (run in another activated Python terminal):

```powershell
python -m bridge.verify_archive --year 2024 --meeting Austin --session Race --start 600 --duration 120
```

This exits nonzero when access/selection fails and reports topic availability without tokens or raw records. A successful response proves retrieval, not GPS calibration.

If archive access remains restricted, capture a real live test clip:

```powershell
python -m bridge.server --record recordings/livef1-small.json.gz
# Wait for real feed messages, then Ctrl+C.
python -m bridge.server --idle --allow-test --recording recordings/livef1-small.json.gz
```

## Tests and merge gate

Automated Python tests cover nested/indexed deltas, identity retention, deletion/null semantics, installed compressed parsers, topic contracts, session transitions, archive seeding/cache bounds, explicit authentication failure, WebSocket snapshot/reconnect, TEST playback/pause and production-control rejection. JavaScript tests cover normalized state, reconnect backoff, stale GPS against the virtual clock, circuit selection, coordinate helpers and renderer features. These fixtures do not prove actual F1 feed positioning.

Executed here: 15 Python tests (including local WebSocket integration), 8 JavaScript tests, production build, lint and diff checks passed. Browser smoke execution was blocked by a missing Chromium binary; browser installation failed on a truncated download. No browser/visual result is claimed.

Before merging: run the authenticated capability probe and a short real Austin TEST clip locally; check live subscription when available. PR is draft until this verification is recorded. PR #1 is the prerequisite. No OpenF1 deletion or hardware deployment is included.

## OpenF1 retirement inventory (retained until replacement verified)

| Existing code/data | Current treatment / replacement |
|---|---|
| `scripts/downloadReplay.mjs`, `downloadMontreal2026.mjs`, `prepareMontrealReplay.mjs`, `downloadAustinReplay.mjs` | Legacy OpenF1 download/preparation; retained for now, not used by LIVE/TEST. |
| `ReplayRace.jsx`, `TimingTower.jsx`, `utils/retirements.js`, Montréal `CircuitMap.jsx` | Legacy replay/timing model; retained, explicitly development-only navigation. Shared useful geometry is not deleted. |
| `AustinReplay.jsx`, `public/data/austin-2026-race.json` (not committed) | Legacy replay/editor prototype; retained development-only, not the new historical testing implementation. |
| `public/data/*.json`, `public/data/montreal-2026-race/` | Old OpenF1 fixtures; retained until authenticated LiveF1 replacement passes the merge gate. |
| `tracks/austin.js` OpenF1 source entry | Retained only for legacy replay; LIVE and TEST exclusively use LiveF1 source coordinates/reference. |
| Jolpica requests in `App.jsx` | Separate calendar/standings integration, **not OpenF1**; unchanged in Milestone 1. LiveF1-only calendar/standings coverage requires a later explicit migration. |

Later milestones own GPS buffer/interpolation improvements and measured calibration (2), official annotations/editor (3), verified circuit registry/workflow (4), flags/automatic session switching (5), and standalone deployment readiness (6). None are claimed complete here.
