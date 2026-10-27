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

## PR #4 refinement: eliminate presentation-rate pulsing

This section supersedes the original clock-slew and buffer-adjustment behavior described above. Same branch and PR; no calibration or trajectory change.

### What the fixed-buffer report revealed

A manual 1,000 ms buffer still went through two velocity feedback loops: `sync()` changed source clock rate by up to ±10% from individual packet phase errors, and `frame()` advanced the cursor toward a changing target with a 110% catch-up ceiling. A fixed delay did not disable those loops. TEST ticks also captured their time before awaiting variable event/broadcast work. Clock packets/heartbeats could therefore describe an earlier point on the timeline than their actual send time. These are code-level causes that can pulse constant-velocity input; they do not prove the real Austin GPS is uniformly smooth.

### Refined timeline

- The backend uses a piecewise-affine monotonic playback clock: source offset = anchor offset + elapsed monotonic time × selected rate. Tick intervals do not integrate into its rate. Pause/speed controls account for elapsed time at the old rate first. Outgoing transport timestamps are computed after event delivery work, separately from archived topic timestamps. `transportMs` makes the backend's actual source-time/wall-time derivative observable.
- In TEST, the frontend clock and presentation cursor run at exactly the selected rate between explicit play/pause/speed/restart controls. Periodic clock packets measure phase error but **do not modulate velocity**. On the same local device, monotonic clocks have the same nominal rate; a small constant packet-delay phase offset is acceptable and remains visible. This is not the old phase-chasing servo.
- In LIVE, packet jitter also leaves rate nominal. Only sustained phase error outside a 50 ms deadband is considered, using a robust 30-second window. Correction is limited to ±0.1% (1,000 ppm), held for at least 30 seconds; a reversal requires an interval at nominal rate. There is no packet-by-packet ±10% adjustment.
- Adaptive buffer statistics remain visible, but chosen delay is **locked when priming**. Recommendations changing during normal running do not alter speed. A genuine widespread underrun can hide/re-prime (at most once per 5 seconds); it does not repeatedly accelerate/decelerate cars to refill a buffer. Manually changing buffer mode/value is an explicit re-prime, so it can briefly hide markers. It is not a CSS easing operation.
- Missing data, spike rejection, stale hiding, driver IDs, calibration projection and linear interpolation between measured GPS samples remain intact. No Hermite trajectory, synthetic telemetry, speed flattening or unlimited extrapolation was introduced.

### Measure source versus animation speed

Expand **Animation diagnostics** while playing your existing clip. It records only while open and retains at most 3,600 animation frames. Select a driver; a new selection clears the trace. The plots show:

1. **Timeline rate / selected playback speed.** In TEST this should remain at 1.000 while playing, including with irregular delivery. Pause is 0. The clock plot should not oscillate at every packet/heartbeat. The numeric header also shows backend rate, phase error, correction ppm, locked buffer, recommended buffer, actual effective delay and rebuffer count.
2. **GPS-implied versus rendered speed**, in native coordinate units per *source* second (not metres/s). `sourcePathSpeed` measures distance along the actual GPS polyline over the rendered source-time interval. `renderedPathSpeed` measures the same traveled polyline distance per wall time, divided by selected TEST speed. Their ratio isolates timeline-rate error. `renderedChordSpeed` uses the direct distance between successive drawn positions and can dip for a frame crossing a corner even when polyline travel speed is unchanged.

Click **Export bounded CSV trace** after 20–40 seconds. Columns include source/presentation/wall clocks, measured presentation rate, frontend/backend rates, phase error, locked/recommended/effective buffer values, GPS segment duration, segment speed, source-path speed, rendered-path/chord speeds, repeated-coordinate flags and motion state. No account credentials, tokens or messages are included. The trace records mathematical marker positions, not an independent browser video or FPS observation.

Interpretation:

- Stable source-implied speed plus varying presentation rate implicates the animation timeline.
- A flat normalized rate with GPS-implied speed pulses, repeated coordinates or alternating source intervals implicates the source sampling/quantization. That alone does **not** establish actual vehicle braking/acceleration.
- Flat path-speed comparison with chord-speed dips confined to direction changes indicates polyline/frame geometry. We do not invent a smooth path to conceal that effect.
- Underrun/recovery/rebuffer events indicate data availability limits; compare them with packet cadence and rejected counts.

### Exact local update and comparison

Stop both running processes, then from your existing checkout:

```powershell
git switch feat/livef1-smooth-animation
git pull --ff-only origin feat/livef1-smooth-animation
.\.venv\Scripts\Activate.ps1
python -m pip install -r bridge/requirements.txt
python -m unittest discover -s bridge/tests -v
python -m bridge.server --login --idle --allow-test
```

In another terminal:

```powershell
npm ci
npm test
npm run lint
npm run build
npm run dev
```

Keep your existing `public/circuits/austin-calibration.json`; no recalibration or cache deletion is needed. Load the same authenticated 2026 Austin TEST clip/window you used before.

1. Select 1× and manual buffer **1,000 ms**, then allow the one-time re-prime. Choose a driver in Animation diagnostics and record a straight section and several corners. Confirm flat normalized presentation rate and compare the two speed plots.
2. Export the trace. Repeat with automatic mode; its recommended delay may move, but locked/effective delay and rate should not follow a periodic cycle during healthy interpolation. Rebuffer count should stay unchanged unless availability genuinely fails.
3. Repeat at 2×, 5× and 10×. Speeds in the source-speed plot are normalized by selected playback rate, so they can be compared across modes.
4. Test pause/resume, speed changes, clip restart and clip switching. Pausing must freeze the cursor; resuming must preserve position. A restart/switch intentionally resets buffers and traces.
5. Check LIVE with real data when available. Sustained correction should stay within ±1,000 ppm and should not flip on every packet.

Regression tests now isolate fixed-buffer jitter, exact selected-rate playback, changing adaptive recommendations, bounded LIVE drift corrections, irregular GPS intervals, curve chord/path measurements, quantized/repeated samples, pause/resume/restart, monotonic backend scheduling and send-time transport stamping. Existing tests remain in place. Actual visual behavior with the user's authenticated Austin data is still a local verification gate; no such observation is claimed here.

### Austin trace: waiting and late GPS recovery

An authenticated Austin export (3,600 frames, driver 1) showed 12 transitions from waiting to interpolation. Waiting lasted roughly 24–279 ms in those windows, with a stable presentation rate. A 194 ms hold was followed by a 6.1 ms frame reporting ~22,375 native units/source second against a ~697-unit source segment. The rendered chord also spiked, so this was a displayed position discontinuity, not just a path-speed calculation artifact. Two gaps of 12 and 47 seconds separate trace sections; they must not be interpreted as continuous playback. Observed GPS segment durations had a median of about 280 ms and a 10th–90th percentile range of about 180–400 ms in the recorded interpolating frames (frame-weighted, not independent sample statistics).

When the presentation cursor outruns the newest sample, the old code held its endpoint but kept advancing the cursor. A late sample then allowed evaluation at the advanced cursor and compressed the accumulated displacement into one frame. Some transitions recur roughly one second apart, consistent with batched delivery, but this export has no packet-arrival or raw-position fields; it cannot prove whether batching, source gaps, or network/bridge scheduling caused those particular underruns. Source GPS quantization and corner dynamics also require raw samples to assess.

Automatic mode now includes observed source-clock-to-newest-sample delivery age in its buffer recommendation, and re-primes after a sustained widespread underrun. The clock is never sped up to catch up. A single driver that underruns holds its last measured point; when late data arrives, the marker is temporarily hidden during reacquisition rather than drawing an instantaneous jump. If continuous samples are unavailable the marker may pause or disappear, including in manual mode; a fixed manual buffer is not silently increased. Once enough samples bracket the cursor, it reappears at the measured interpolated position. This is an explicit loss-of-continuity tradeoff, not a claim that missing motion was reconstructed. The calibration is unchanged. Trace path speed is blank for transitions involving waiting; chord speed still reports actual visible frame displacement, with no cross-recovery measurement.

To verify, update this PR branch and run the backend and frontend as described above. Load the same authenticated Austin TEST clip, open Animation diagnostics, select driver 1, and compare automatic mode with manual 1000 ms at 1× and higher speeds. Check the GPS delivery age p95, recommended versus locked delay, underruns, rebuffers and per-driver waiting/recovering states. Allow a re-prime after a widespread underrun; the locked delay changes only on re-prime. Export a fresh trace and check that waiting-to-interpolation does not create extreme displayed chord spikes. A marker that repeatedly disappears indicates insufficient delivery headroom or missing samples; increase the manual buffer only for diagnosis, or use automatic mode. The trace has not been visually verified by the implementer with authenticated data.
