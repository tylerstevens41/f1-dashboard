# Reusable circuit system

`CircuitRenderer.jsx` owns Austin track layers, annotations and driver drawing for both live and replay. `LiveCircuitSvg.jsx` remains the live loading/freshness/control wrapper. `AustinReplay.jsx` retains its clock, timing, interpolation and existing browser-local editor. Montréal's existing renderer and timing behavior remain available.

## Coordinates

The decorative `public/circuits/austin.svg` is not calibrated to either feed and is deliberately not used as a GPS coordinate frame.

Each source in `tracks/austin.js` declares an affine matrix `[a,b,c,d,e,f]`: `x'=a*x+c*y+e`, `y'=b*x+d*y+f`. Geometry and cars pass through the same source transform, followed by bounds translation, Y inversion and display padding.

LiveF1 uses `austin-gps-reference.json`. OpenF1 uses the lap reference embedded in its replay. Identity matrices mean each feed is displayed in its own reference frame; they do **not** assert the feeds have equal coordinates. Aligning OpenF1 positions to the LiveF1 reference or to the decorative SVG requires measured control points and a validated calibration first.

## Stable circuit annotations

Austin config supports corners `{number,at,offset:{x,y}}`, detection points `{id,at,label}`, activation zones `{id,start,end,label}`, sectors `{at,label}` and `startFinish:{at,label}`. Positions are fractions of cumulative centreline length, in travel order, independent of car GPS updates. Zones can wrap through start/finish. Flag colors are a configurable renderer input; live flag subscription is not added in this change.

Official annotation arrays are intentionally empty pending calibration. Austin OpenF1 replay disables shared annotations because its generated reference may start at a different lap phase or have a different shape. Enable them only after its reference has been aligned to the canonical geometry and geometry version. Legacy editor markers remain local and unchanged; they are not silently converted into official circuit features.

## Local checks

Use Node 24 (Node's test runner and Vite are required):

```sh
npm ci
npm test
npm run build
npm run lint
npm run dev
```

Open Dashboard → Live Race. LIVE uses the existing Python bridge:

```sh
python -m pip install livef1 websockets
python livef1-test/live_bridge.py
```

Verify tower updates, selected driver, team colours, labels and GPS controls. REPLAY runs the committed Montréal dataset. Austin Replay uses the shared renderer; its large dataset is not committed. To obtain it, run:

```sh
node scripts/downloadAustinReplay.mjs
```

This downloads from OpenF1 and can take considerable time. Then select Austin Replay, play/seek/change speed and check marker selection and existing corner/DRS placement. Official calibration and actual feed correctness require source samples and visual verification, beyond build/unit checks.
