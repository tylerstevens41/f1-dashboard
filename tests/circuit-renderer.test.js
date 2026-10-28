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

test('verified unequal sectors render along calibrated path; provisional colours require preview', async () => {
 const server=await createServer({server:{middlewareMode:true},appType:'custom'});
 try {
  const {default:Renderer}=await server.ssrLoadModule('/src/circuits/CircuitRenderer.jsx');
  const {emptyAnnotations}=await server.ssrLoadModule('/src/circuits/annotations.js');
  const geometry=createGeometry([{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100},{x:0,y:0}]);
  const config={...emptyAnnotations(austin,geometry),startFinish:{at:.8,status:'provisional'},sector1End:{at:.05,status:'provisional'},sector2End:{at:.5,status:'provisional'},corners:[{number:7,at:.1,offset:{x:90,y:-40},status:'provisional'}]};
  const props={geometry,circuit:austin,annotations:config,flag:'RED'};
  const missing=renderToStaticMarkup(createElement(Renderer,props));
  assert.doesNotMatch(missing,/data-sector=/);assert.doesNotMatch(missing,/T7/);assert.match(missing,/data-layer="race-control"/);
  const preview=renderToStaticMarkup(createElement(Renderer,{...props,previewProvisional:true}));
  assert.equal((preview.match(/data-sector=/g)||[]).length,4);assert.match(preview,/#ed3897/);assert.match(preview,/#f6ce42/);assert.match(preview,/#40bff2/);assert.match(preview,/data-corner="7"/);
  const verified={...config,startFinish:{...config.startFinish,status:'verified'},sector1End:{...config.sector1End,status:'verified'},sector2End:{...config.sector2End,status:'verified'}};
  const production=renderToStaticMarkup(createElement(Renderer,{...props,annotations:verified}));assert.equal((production.match(/data-sector=/g)||[]).length,4);
 } finally {await server.close();}
});

test('all twenty imported corners render without provisional toggle; manual drafts preview immediately', async()=>{
 const server=await createServer({server:{middlewareMode:true},appType:'custom'});
 try {
  const {default:Renderer}=await server.ssrLoadModule('/src/circuits/CircuitRenderer.jsx');
  const {emptyAnnotations,placeAnnotation}=await server.ssrLoadModule('/src/circuits/annotations.js');
  const geometry=createGeometry([{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100},{x:0,y:0}]);
  const data={...emptyAnnotations(austin,geometry),corners:Array.from({length:20},(_,i)=>({number:i+1,letter:i===1?'A':'',at:i/20,status:'provisional',imported:true}))};
  const html=renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations:data}));
  assert.equal((html.match(/data-layer="corner"/g)||[]).length,20);assert.match(html,/data-corner="2A"/);
  const placed=placeAnnotation(data,{kind:'startFinish'},.1);
  const preview=renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations:placed,previewProvisional:true,annotationSelection:{kind:'startFinish'}}));
  assert.match(preview,/data-layer="start-finish"/);assert.match(preview,/data-layer="editor-selection"/);
  const hidden={...data,corners:data.corners.map(c=>({...c,hidden:true}))};
  assert.doesNotMatch(renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations:hidden})),/data-layer="corner"/);
 }finally{await server.close();}
});

test('larger standalone corner circles retain offsets, fit suffixes and stay inside the viewBox', async()=>{
 const server=await createServer({server:{middlewareMode:true},appType:'custom'});
 try {
  const {default:Renderer}=await server.ssrLoadModule('/src/circuits/CircuitRenderer.jsx');
  const {defaultAppearance}=await server.ssrLoadModule('/src/circuits/annotations.js');
  const geometry=createGeometry([{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100},{x:0,y:0}]);
  const annotations={corners:[{number:20,letter:'A',at:0,offset:{x:-600,y:-800}}]};
  const before=JSON.stringify(annotations);
  const markup=renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations,appearance:{...defaultAppearance,cornerLabelSpacing:1}}));
  const group=markup.match(/<g data-layer="corner"[^>]*>(.*?)<\/g>/s)[1];
  assert.doesNotMatch(group,/<line\b/);assert.match(group,/20A/);
  const circle=group.match(/<circle cx="([^"]+)" cy="([^"]+)" r="([^"]+)"/);
  assert.equal(Number(circle[1]),50);assert.equal(Number(circle[2]),-50);
  assert.ok(Number(circle[3])>=155*1.5);
  const box=markup.match(/viewBox="([^"]+)"/)[1].split(' ').map(Number);
  assert.ok(box[0]<50-Number(circle[3]));assert.ok(box[1]<-50-Number(circle[3]));
  assert.match(markup,/preserveAspectRatio="xMidYMid meet"/);
  const smaller=renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations,appearance:{...defaultAppearance,cornerLabelScale:1}}));
  assert.match(smaller,/r="155"/);assert.equal(JSON.stringify(annotations),before);
  const spaced=renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations}));
  assert.match(spaced,/<circle cx="-40" cy="-169.9999999999999"|<circle cx="-40" cy="-170"/);
  assert.equal(JSON.stringify(annotations),before);
 }finally{await server.close();}
});

test('calculated provisional boundaries render automatically with unequal colours and finish marker',async()=>{
 const server=await createServer({server:{middlewareMode:true},appType:'custom'});
 try {
  const {default:Renderer}=await server.ssrLoadModule('/src/circuits/CircuitRenderer.jsx');
  const {emptyAnnotations}=await server.ssrLoadModule('/src/circuits/annotations.js');
  const geometry=createGeometry([{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100},{x:0,y:0}]);
  const mark=at=>({at,status:'provisional',calculated:true});
  const data={...emptyAnnotations(austin,geometry),startFinish:mark(.8),sector1End:mark(.05),sector2End:mark(.5)};
  const html=renderToStaticMarkup(createElement(Renderer,{geometry,circuit:austin,annotations:data}));
  assert.equal((html.match(/data-sector=/g)||[]).length,4);
  assert.match(html,/data-layer="start-finish"/);assert.match(html,/#ed3897/);assert.match(html,/#f6ce42/);assert.match(html,/#40bff2/);
 }finally{await server.close();}
});
