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

test('wall mirrors the shared manual LIVE presentation without inheriting developer tab navigation or TEST',()=>{
 const manual={mode:'MANUAL',view:'dashboard',manualPresentation:'live'};
 assert.equal(controllerView(manual,'dashboard',{wall:true,dataMode:'LIVE'}),'live');
 assert.equal(controllerView(manual,'dashboard',{wall:false,dataMode:'LIVE'}),'dashboard');
 assert.equal(controllerView(manual,'live',{wall:true,dataMode:'TEST'}),'dashboard');
 assert.equal(controllerView({...manual,manualPresentation:'dashboard'},'live',{wall:true,dataMode:'LIVE'}),'dashboard');
 const auto={mode:'AUTO',state:'LIVE',view:'live'};
 let race=raceReducer(initialRaceState(),{version:1,type:'snapshot',generation:1,sequence:1,mode:'LIVE',topics:{},controller:{mode:'AUTO',view:'dashboard'}});
 race=raceReducer(race,{version:1,type:'status',generation:1,sequence:2,mode:'LIVE',controller:auto});
 assert.equal(controllerView(race.controller,'dashboard',{wall:true,dataMode:race.mode}),'live');
 race=raceReducer(race,{version:1,type:'status',generation:1,sequence:3,mode:'LIVE',controller:{...auto,state:'DASHBOARD',view:'dashboard'}});
 assert.equal(controllerView(race.controller,'live',{wall:true,dataMode:race.mode}),'dashboard');
});

test('wall App renders race rather than zero-countdown Dashboard from shared backend control snapshots',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true,hmr:false,watch:null},appType:'custom',plugins:[{
  name:'synthetic-wall-feed',enforce:'pre',transform(code,id){
   if(id.split('?')[0].endsWith('/src/App.jsx'))return code
    .replace('import useRaceFeed from "./race/useRaceFeed";','const useRaceFeed=()=>globalThis.__syntheticWallFeed;')
    .replace('const [nextRace, setNextRace] = useState(null);','const [nextRace,setNextRace]=useState({date:"2000-01-01",time:"00:00:00Z",round:"SIMULATION",raceName:"Las Vegas synthetic fixture",Circuit:{circuitId:"fixture",circuitName:"Fixture",Location:{locality:"Las Vegas"}}});');
  }
 }]});
 const oldWindow=globalThis.window;
 try {
  globalThis.window={location:{pathname:'/wall',search:''}};
  const {default:App}=await server.ssrLoadModule('/src/App.jsx');
  const race={...initialRaceState(),mode:'LIVE',upstream:'connected',topics:{SessionInfo:{Name:'Race',Meeting:{Name:'Las Vegas Grand Prix (synthetic fixture)'}}},controller:{mode:'AUTO',state:'LIVE',view:'live'}};
  globalThis.__syntheticWallFeed={race,connection:'connected',clockMs:0,preparedBundles:{},circuitJobs:{},send(){},animation:{configure(){}}};
  const render=()=>renderToStaticMarkup(createElement(App));
  assert.match(render(),/LIVE TIMING/);assert.doesNotMatch(render(),/LIGHTS OUT IN|Development diagnostics/);
  race.controller={mode:'MANUAL',view:'dashboard',manualPresentation:'live'};
  assert.match(render(),/LIVE TIMING/);assert.doesNotMatch(render(),/LIGHTS OUT IN/);
  race.mode='TEST';assert.doesNotMatch(render(),/LIVE TIMING/);
  race.mode='LIVE';race.controller={mode:'AUTO',state:'DASHBOARD',view:'dashboard'};
  assert.doesNotMatch(render(),/LIVE TIMING/);assert.match(render(),/LIGHTS OUT IN/);assert.equal((render().match(/>00<\/strong>/g)??[]).length,4);
 }finally{globalThis.window=oldWindow;delete globalThis.__syntheticWallFeed;await server.close();}
});
