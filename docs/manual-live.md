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
