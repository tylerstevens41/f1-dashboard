import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {tyreAsset} from '../src/race/tyres.js';
import {viewAccess} from '../src/race/controllerView.js';
import {initialRaceState} from '../src/race/state.js';

test('compound aliases use existing artwork and safe base URLs; unknowns never guess',()=>{
 for(const [name,aliases] of Object.entries({soft:['SOFT','s',' Soft '],medium:['MEDIUM','m'],hard:['HARD','h'],intermediate:['INTERMEDIATE','i','inters','Inter'],wet:['WET','w','Full Wet','full_wet']})){
  for(const alias of aliases)assert.deepEqual(tyreAsset(alias,'/dashboard/'),{name,src:`/dashboard/tyres/${name}.svg`});
  assert.ok(existsSync(`public/tyres/${name}.svg`));
  assert.match(readFileSync(`public/tyres/${name}.svg`,'utf8'),/viewBox="0 0 500 500"/);
 }
 for(const unknown of [null,undefined,'','UNKNOWN','C3','experimental'])assert.equal(tyreAsset(unknown),null);
 assert.equal(tyreAsset('S').src,'/tyres/soft.svg');
});

test('shared LIVE/TEST tower renders SVG compounds, updates stints and isolates developer controls',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true,hmr:false,watch:null},appType:'custom'});
 try {
  const {default:Race}=await server.ssrLoadModule('/src/LiveRace.jsx');
  const {default:Circuit}=await server.ssrLoadModule('/src/circuits/LiveCircuitSvg.jsx');
  const circuitHtml=renderToStaticMarkup(createElement(Circuit,{circuitName:'Austin',readOnly:true}));
  assert.doesNotMatch(circuitHtml,/Calibration:|Labels|GPS calibration overlay|checkbox|Animation diagnostics/);
  const devCircuit=renderToStaticMarkup(createElement(Circuit,{circuitName:'Austin',readOnly:false}));
  assert.match(devCircuit,/GPS calibration overlay/);
  const race={...initialRaceState(),topics:{DriverList:{1:{Tla:'VER',TeamColour:'FFFFFF'}},TimingAppData:{1:{Stints:{0:{Compound:'SOFT',TotalLaps:5}}}}},capabilities:{}};
  const feed={race,connection:'connected',clockMs:0,preparedBundles:{},circuitJobs:{},send(){},animation:{configure(){}},sessions:[],liveSessions:[],controls:true};
  const render=props=>renderToStaticMarkup(createElement(Race,{feed,...props}));
  for(const mode of ['LIVE','TEST']){
   race.mode=mode;
   for(const props of [{},{wall:true},{wall:true,developer:true}]){
    const html=render(props);
    assert.match(html,/src="\/tyres\/soft.svg"/);assert.match(html,/5L/);
    assert.doesNotMatch(html,/LEGACY OPENF1|Legacy Austin Replay|Development diagnostics|Discover race sessions|Start LIVE|Archive year|GPS transport|drivers with GPS data|relative archive clock/);
   }
  }
  const dev=render({developer:true});assert.match(dev,/Development diagnostics/);assert.match(dev,/Discover race sessions/);assert.match(dev,/Historical LiveF1 session/);
  race.topics.TimingAppData[1].Stints[1]={Compound:'HARD',TotalLaps:0};
  assert.match(render({}),/src="\/tyres\/hard.svg"/);assert.doesNotMatch(render({}),/soft.svg/);
  race.topics.TimingAppData[1]={};assert.doesNotMatch(render({}),/src="\/tyres\//);assert.match(render({}),/Tyre compound unavailable/);
 } finally {await server.close();}
});

test('only /dev enables tools; root and wall remain production views',()=>{
 assert.deepEqual(viewAccess('/'),{wall:false,developer:false});
 assert.deepEqual(viewAccess('/dev'),{wall:false,developer:true});
 assert.deepEqual(viewAccess('/wall'),{wall:true,developer:false});
 assert.deepEqual(viewAccess('/dev','?wall=1'),{wall:true,developer:false});
});
