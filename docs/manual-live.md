# Manual LIVE race tracking

LIVE existed before this change: the backend subscribed to the current upstream
feed automatically unless started with `--idle`; the only browser action was
Return to LIVE inside development diagnostics, gated incorrectly by TEST permission.
There was no visible independent stop/discovery control. The shared live feed,
normalizer, state, interpolation, timing tower and native-coordinate checks remain
unchanged. No prepared Brazil/Austin/Mexico/Suzuka assets are generated or modified.

## Windows quick start

```powershell
git switch feat/automatic-circuit-preparation
git pull --ff-only origin feat/automatic-circuit-preparation
.\.venv\Scripts\python.exe -m bridge.server --idle --allow-test --login
```

In another terminal:

```powershell
npm run dev
```

Open the dashboard's Live Race page. The always-visible LIVE strip works even
without `--allow-test` (that flag only retains the historical controls).

1. Click **Start LIVE** with **Current LIVE feed (automatic)** selected. This
   joins the actual live feed mid-session, not an archive or a race replay.
2. Optionally click **Discover race sessions** and select the published current
   Sao Paulo Race, then Start LIVE. Candidates are actual current-year Race
   metadata within one day of UTC today; their existence is not proof of activity.
   No session key/path is hardcoded. Discovery errors do not prevent using the
   current live-feed option. Retry discovery if the race is not published yet.
3. The live endpoint always serves its current session. Selecting a candidate
   validates that feed identity; it cannot route the endpoint to another session.
   Mismatch shows a waiting message and suppresses non-session telemetry. No
   historical substitution occurs. A reconnect requires identity confirmation again.
4. Confirm the displayed actual meeting/session is Sao Paulo Race, then wait for
   **Receiving LIVE GPS telemetry**. This requires SessionInfo plus nonzero finite
   GPS samples within five seconds, not merely a local WebSocket connection.
5. Prepared circuit lookup uses the incoming actual circuit key and season. The
   existing dynamic asset store supplies geometry, corners and sectors without
   imports or rebuilding. The circuit's existing runtime GPS compatibility warning
   and marker gate still apply: a displayed outline alone does not prove alignment.
6. Check driver motion, team abbreviations, timing updates and freshness diagnostics.
   Stop LIVE cancels the source and clears the live buffers/state. Existing TEST
   controls still load real archived clips; Start LIVE clears TEST clip/timeline.

## Status and recovery

The strip distinguishes local WebSocket disconnection, LiveF1 connecting,
authentication/connection/subscription errors, waiting for session metadata or
selected-session identity, connected awaiting GPS, receiving fresh GPS, stale
GPS and ended/finalised sessions. These are observed transport/data conditions,
not proof that a physical car is precisely aligned. Missing/stale positions keep
the existing interpolation protection; no new extrapolation/snap behavior exists.

LiveF1 1.3.0's existing reconnect loop/backoff is retained. Safe stream errors now
remain distinguishable rather than being overwritten immediately by disconnected.
The live client subscribes to SessionInfo, DriverList, Position.z, TimingData,
TimingAppData, CarData.z, TrackStatus, RaceControlMessages, SessionStatus and
SessionData. Its subscription snapshot permits mid-session joining. Credentials
stay in the backend; run `--login` locally if required. No token or raw provider
exception is sent to the frontend. Stop/start lets the user retry manually.

If the actual race has ended, SessionStatus can show Session ended. Start LIVE
never loads an old TEST clip to simulate a race. A previously cached upstream
session can be shown while waiting, but stale UTC GPS must not be labelled fresh.
Optional selected-session validation blocks data from a different feed identity.

## Verification and limits

Tests simulate subscription snapshots/deltas, session discovery, independently
authorized LIVE controls, TEST isolation, start/stop/reconnect reset, mismatch
suppression, real-metadata circuit lookup without regeneration, status freshness,
ended sessions and visible controls without TEST permission. Existing WebSocket
reconnect, dynamic registry, decoder, timing and animation regressions also run.
No real authenticated LIVE connection or local Brazil circuit asset was available
in this environment. Do not claim race GPS or browser alignment is verified until
local fresh telemetry and compatible marker movement are observed.

## LIVE burst/freshness flicker correction

Two reproducible code defects were found after the Brazilian LIVE report:

- `gpsCompatibility` rebuilt a five-driver quorum from samples less than 2,500 ms
  old on every render. A short delivery gap returned waiting-for-gps and removed
  the entire marker subtree, even when measured circuit alignment had passed.
- `AnimationEngine.evaluate` rejected samples older than 2,500 ms against source
  UTC before checking whether they still bracketed its delayed presentation cursor.
  Its existing buffer can be as large as 5,000 ms, so valid buffered samples could
  be declared stale before they were displayed.

A session/geometry-scoped CompatibilityTracker now accumulates at most one latest
on-track position per driver over a bounded 30-second evidence window. The same
five-driver minimum and 3%-extent p95 limit still apply; alignment success survives
missing data within the same source generation. New incompatible evidence blocks
markers; individually incompatible driver coordinates are withheld. A mode/source
session/generation remount or geometry change creates a new tracker. No geometry
approval is reused after reconnect/reset. Retained geometry evidence is **not** a
claim of fresh telemetry and does not keep stale markers alive.

For LIVE only, the stale check credits the actual source-minus-presentation delay,
capped by the existing 5-second maximum buffer. It still expires a driver after
2.5 seconds beyond the delayed cursor and never permits wall-clock sample age
beyond 7.5 seconds with default settings. TEST thresholds/clocks are unchanged.
Positions are interpolated only between measured samples; after a buffer underrun
only the existing bounded hold/recovery behavior applies. No extrapolation,
track snapping, coordinate recalibration or buffer-target enlargement was added.

### Diagnosing the next authenticated run

Pull the branch, stop the existing backend/Vite processes with Ctrl+C and restart
using the Windows commands above. Do not rerun circuit preparation or delete any
assets/caches. Hard-refresh the browser and Start LIVE.

Expand **Development diagnostics** and **Animation diagnostics**. The circuit
panel shows alignment evidence count, newest GPS UTC age, recent-driver count,
last actual alignment success age and invalid/future/old/off-track evidence counts.
The geometry status may read `compatible-retained` during a short delivery gap;
that is expected. The LIVE strip may independently report stale telemetry.

The diagnostic chain distinguishes:

1. Backend raw Position.z messages and last UTC receipt.
2. Normalized receipt/sample UTC, driver counts, coordinate rejections, missing
   source-UTC history and session-identity drops.
3. Frontend GPS message receipt and local WebSocket opens/closes.
4. Last interpolation-buffer acceptance age, per-driver rejection reasons,
   source-UTC sample age versus presentation-cursor age.
5. Last real geometry-alignment success, not a refresh-driven timestamp.
6. Last DOM marker placement age (not proof that a browser paint was visible).
7. Upstream connection attempts/losses and subscription snapshot count, along
   with the engine reset/rebuffer reason and current session/generation.

Backend/frontend receipt clocks are UTC epoch milliseconds; animation acceptance
and DOM intervals use the browser monotonic clock. `_sampleTimeMs` derives from
Position.z Utc (frame UTC fallback exists for records without Utc, but interpolation
requires actual source history). No arbitrary cross-clock correction is introduced.
Compare ages, not raw monotonic values with UTC. Large browser/server UTC skew
still requires checking the local machine clock; it is not silently compensated.

A deterministic regression uses 1-second delivery bursts with measured GPS 3 seconds
behind source UTC. The old global gate reports waiting and the old animation stale
check hides valid delayed brackets. The updated pipeline stays interpolating across
those deliveries; after a true outage the driver expires. Additional tests cover
asynchronous drivers, retained evidence, incompatible coordinates, fresh epoch
reset, independent staleness and TEST isolation. This proves the code defects and
fixture correction, **not** the actual cadence/clock skew of the user's live feed.
Real authenticated LIVE visual success still requires local confirmation and the
new diagnostics if flicker remains.
