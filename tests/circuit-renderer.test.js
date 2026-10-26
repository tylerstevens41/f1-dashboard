import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createGeometry } from '../src/circuits/geometry.js';
import austin from '../src/circuits/tracks/austin.js';

test('shared renderer supports replay markers, calibrated features and flags', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
  try {
    const { default: Renderer } = await server.ssrLoadModule('/src/circuits/CircuitRenderer.jsx');
    const geometry = createGeometry([{x:0,y:0},{x:10,y:0},{x:10,y:10}]);
    const props = { geometry, circuit:austin, flag:'YELLOW',
      drivers:[{driver_number:1,x:650,y:660,color:'#123456',label:'VER'}],
      annotations:{corners:[{number:1,at:0.25}], zones:[{id:'zone',start:0.8,end:0.2}], startFinish:{at:0,label:'START'}} };
    const markup = renderToStaticMarkup(createElement(Renderer, props));
    assert.match(markup,/T1/); assert.match(markup,/VER/);
    assert.match(markup,/#123456/); assert.match(markup,/#ffd43b/);
    assert.equal((markup.match(/pathLength="1"/g) ?? []).length,2);
    const uncalibrated = renderToStaticMarkup(createElement(Renderer, {...props,annotationsCalibrated:false}));
    assert.doesNotMatch(uncalibrated,/T1/);
    const animated = renderToStaticMarkup(createElement(Renderer, {...props,animate:true,animation:{subscribe:()=>()=>{}}}));
    assert.match(animated,/data-driver="1"/);
    assert.match(animated,/VER/);
    assert.match(animated,/visibility:hidden/);
    const { default: Layers } = await server.ssrLoadModule('/src/circuits/CalibrationLayers.jsx');
    const overlay=renderToStaticMarkup(createElement(Layers,{geometry,circuit:austin,calibration:{debug:{raw:[[0,0]],accepted:[[10,10]]}},layers:{raw:true,transformed:true,original:true}}));
    assert.match(overlay,/austin.svg/);
    assert.match(overlay,/#ff8040/);
  } finally { await server.close(); }
});
