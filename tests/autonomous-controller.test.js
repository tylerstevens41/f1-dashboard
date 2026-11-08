import {test} from 'node:test';
import assert from 'node:assert/strict';
import {controllerView} from '../src/race/controllerView.js';
import {initialRaceState,raceReducer} from '../src/race/state.js';
test('AUTO view is authoritative; manual navigation and TEST remain explicit',()=>{
 for(const view of ['dashboard','live'])assert.equal(controllerView({mode:'AUTO',view},'live'),view);
 assert.equal(controllerView({mode:'MANUAL',view:'live'},'dashboard'),'dashboard');
 assert.equal(controllerView(null,'live'),'live');
});
test('controller state survives topic deltas and arrives on refresh snapshots',()=>{
 const controller={mode:'AUTO',state:'LIVE_STALE',view:'live',reason:'GPS temporarily missing'};
 const snapshot={version:1,type:'snapshot',generation:1,sequence:1,mode:'LIVE',controller,topics:{}};
 let state=raceReducer(initialRaceState(),snapshot);
 state=raceReducer(state,{version:1,type:'topic',generation:1,sequence:2,mode:'LIVE',topic:'DriverList',data:{1:{Tla:'ABC'}}});
 assert.deepEqual(state.controller,controller);
 assert.deepEqual(raceReducer(initialRaceState(),snapshot).controller,controller);
});
test('read-only circuit view does not render developer controls',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true,hmr:false,watch:null},appType:'custom'});
 try{
  const {default:Race}=await server.ssrLoadModule('/src/LiveRace.jsx');
  // Shared feed: SSR must not create/use a standalone WebSocket hook.
  const race={...initialRaceState(),topics:{},capabilities:{}};
  const html=renderToStaticMarkup(createElement(Race,{wall:true,feed:{race,connection:'connected',clockMs:0,preparedBundles:{},circuitJobs:{},send:()=>{},animation:{configure(){}}}}));
  assert.doesNotMatch(html,/Start LIVE|Discover race sessions|Development diagnostics|Legacy Austin Replay/);
 }finally{await server.close();}
});
