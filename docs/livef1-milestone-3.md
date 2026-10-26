# Milestone 3: continuous LiveF1 animation

Branch `feat/livef1-smooth-animation`, based on `feat/livef1-gps-calibration` (PR #3). PR #4 targets that branch, not main. No existing PR is merged. No calibration JSON, SVG, source reference, coordinate matrix or geometry math is overwritten by this phase. Keep your locally generated `public/circuits/austin-calibration.json`.

## Root causes found in code and reproduced in tests

1. **Newest-sample feedback moved presentation time.** The old marker calculated `delay = max(250*speed, clock.time - latest.time + 250*speed)` on each frame. When latest GPS changed, the delay could shrink immediately even at an unchanged animation timestamp. A regression case reproduces a 100 ms cursor jump just from a packet arrival. Repeating this at every source update produces hopping instead of interpolation through a stable timeline.
2. **Historical event time and transport time were mixed.** TEST emitted topic messages with each archived event's timestamp, while the map re-anchored its extrapolated clock whenever the React `clockMs` changed. Several historical events delivered in one scheduler tick could repeatedly re-anchor the clock. Transport time now has its own `clock` message after each active TEST tick. Topic timestamps update freshness and data, not the animation or UI transport clock.
3. **Rendering was coupled to React's latest state.** Each marker copied its history after React committed, so intermediate WebSocket states depended on React scheduling. Samples now enter the shared animation engine directly in the WebSocket callback, before dispatching to React. Markers subscribe by immutable driver number; standings/tyre/selection rerenders do not restart their movement.
4. **A real batch-loss edge case existed.** The normalizer could reject a whole compressed Position.z batch if its newest record had invalid coordinates. It now retains valid earlier samples, counts invalid samples, and accepts late samples into sorted history without rewinding the latest car fields.
5. **Fixed delay and retention were insufficiently informed.** The old 24-sample history and 250 ms assumption did not account for delivery batching at fast playback. Retention is now 128 source samples/car on the backend; the browser retains up to 512 samples/car or 30 source seconds. Buffer sizing measures source cadence, packet delivery span and delivery jitter. No claim about the actual frequency in the user's authenticated clip is made without running it.

React did not necessarily drop the archived samples in every case: `_history` already preserved many batched samples in PR #3. The new tests distinguish deterministic cursor faults, batch edge cases and bounded retention from unmeasured real-world sparsity.

## Current pipeline

LiveF1 compressed samples → validated, ordered source history → WebSocket topic state → **animation engine immediately** + normal React reducer → one requestAnimationFrame loop → subscribed marker DOM transforms → existing calibrated projection.

Timing data, driver identity, team colors and abbreviations remain in the existing React UI. The calibration transform is applied only to the final interpolated native position. No CSS transitions, extrapolation, racing-line inference or snapping to the outline are used.

### Clock rules

- TEST has explicit transport-clock messages on active scheduler ticks, separate from historical event timestamps. LIVE uses backend clock/status anchors and a monotonic browser clock between them.
- Normal clock updates slew the source clock slightly instead of replacing the rendered position. The presentation cursor never runs backward on a normal packet.
- Automatic delay is `max(2 × p95 source interval, p95 packet-delivery interval × speed + source interval) + p95 jitter`, bounded by circuit configuration (100–5000 **source** milliseconds). Both source and equivalent wall milliseconds are displayed. Delivery statistics reset on pause/resume and speed changes; source cadence is retained.
- Buffer changes slew gradually. A new sample cannot directly rebase the cursor. Source-time velocity scales at 1×/2×/5×/10× without multiplying a fixed 250 ms preset.
- Pause freezes the rendered cursor on the next animation frame, with no catch-up to a newly calculated endpoint. Resume/speed changes retain it. Restart/clip load/session transition/reconnect snapshot clears prior buffers and clock state. A suspended/background animation frame hides before reacquisition rather than drawing a catch-up shortcut.
- There is one active RAF loop for all 20–22 drivers. No React state update is made per animation frame. Diagnostics refresh twice per second in development.

### Missing, sparse and invalid data

Interpolation uses only bracketing measured samples. A missing upper bracket can hold the last known point briefly (`waiting`, an underrun). A source gap above the configured 1500 ms limit hides the marker (`recovering`); no straight segment is drawn across the gap. A new continuous pair is needed to resume after the gap. Source data older than 2500 ms is `stale` and hidden. The conservative native-unit velocity guard remains configurable; it does not assume coordinates are metres. Its rejected count is visible so a bad threshold cannot silently masquerade as missing GPS.

This cannot make genuinely sparse/missing source data precise. If your measured cadence exceeds the gap limit, diagnostics will show recovery/staleness rather than invent a path. Investigate the source clip and timestamps before changing thresholds. Automatic buffering does not override that safety limit.

## Development diagnostics

Expand **Animation diagnostics** in the circuit panel (development only, collapsed by default):

- source GPS Hz per driver (unique source timestamp intervals);
- Position packet delivery Hz;
- samples buffered/car;
- playback/source clock and interpolation clock;
- actual and target buffer delay, including equivalent wall delay;
- underrun episodes and rejected samples (frontend validation plus backend invalid-record counts);
- `interpolating`, `waiting`, `stale`, or `recovering` state.

Select **Manual buffer** to test 0–5000 source milliseconds. Disable it to restore automatic mode. Manual changes intentionally do not reset the cursor. Duplicates are deduplicated, not treated as invalid. All diagnostics and buffer controls are absent from the production interface.

## Exact Windows PowerShell steps

Keep your existing calibrated Austin file. Git should leave that local, untracked file in place; do not run clean/reset commands that delete it.

Backend terminal, from repo root:

```powershell
git fetch origin
git switch --track origin/feat/livef1-smooth-animation
.\.venv\Scripts\Activate.ps1
python -m pip install -r bridge/requirements.txt
python -m unittest discover -s bridge/tests -v
python -m bridge.server --login --idle --allow-test
```

If the branch already exists, use `git switch feat/livef1-smooth-animation`. Authenticate locally using LiveF1 if needed. Never share credentials or tokens.

Frontend terminal:

```powershell
npm ci
npm test
npm run lint
npm run build
npm run dev
```

Open `http://localhost:5173`, select **Live Race → LIVE**, then use the existing development diagnostics to load your known working historical Austin session/window. No recalibration is needed for this phase. Start with automatic buffering at 1× and let it fill briefly. Check:

1. In Animation diagnostics, source GPS Hz is stable/plausible, sample buffers fill and most cars spend sustained periods `interpolating`.
2. On the map, markers move continuously between packet arrivals while keeping the calibrated alignment. Colors and abbreviations follow driver numbers through timing-position changes.
3. Repeat at 2×, 5×, 10×. Source clocks scale, but source timestamps remain unchanged. Occasional waits should correlate with diagnostics, not arbitrary React rerenders.
4. Pause while a car is moving. It should freeze immediately; resume should continue from that rendered cursor. Change speed while playing and verify no position rebase.
5. At clip end press Play to restart. Load another clip/session and verify no old positions leak into it. Reload the browser during playback and verify the snapshot restores bounded histories.
6. Briefly stop the backend/network. Markers should wait, then become stale/hidden. Reconnect and verify reacquisition does not draw a shortcut across the circuit.
7. As a diagnostic comparison only, enable Manual buffer and reduce it toward zero. Underruns may increase. Restore automatic mode afterward.
8. Return to LIVE when an actual session is available and repeat the cadence/underrun check.

The optional real recording fallback remains supported:

```powershell
python -m bridge.server --idle --allow-test --recording recordings/livef1-small.json.gz
```

## Automated evidence and remaining gate

Tests use explicit synthetic protocol/trajectory fixtures, not fabricated race recordings. They cover continuous timestamps, irregular intervals, batched/late/duplicate/invalid samples, streaming batches at all four speeds, pause/resume/speed transitions, clip resets, stale/gap recovery, background suspension, adaptive buffering, calibration projection and 22 stable marker subscriptions. Backend tests exercise compressed LiveF1 parsing, ordered bounded retention, invalid-last-record batches, and broadcast TEST clocks/pause controls through actual local WebSockets.

Run the commands above. Build/lint passing is not visual proof. Authenticated representative Austin data and an actual browser observation remain necessary before merge. No claim of visually verified smooth LiveF1 movement is made here. Keep PR #4 draft pending that local check. Calibration, source geometry, archive bounds and the timing tower remain intact.
