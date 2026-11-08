import {test} from 'node:test';
import assert from 'node:assert/strict';
import {initialRaceState} from '../src/race/state.js';
import {liveTrackingStatus} from '../src/race/liveStatus.js';
test('LIVE status requires metadata and actual fresh nonzero measured GPS',()=>{
 let race={...initialRaceState(),upstream:'connected'};
 assert.match(liveTrackingStatus(race,'connected',10000),/Waiting/);
 race={...race,topics:{SessionInfo:{Name:'Race'}}};
 assert.match(liveTrackingStatus(race,'connected',10000),/awaiting GPS/);
 race.topics['Position.z']={1:{X:100,Y:200,_sampleTimeMs:9800}};
 assert.match(liveTrackingStatus(race,'connected',10000),/Receiving LIVE/);
 assert.match(liveTrackingStatus(race,'connected',18000),/stale/);
 race.topics.SessionStatus={Status:'Finished'};
 assert.equal(liveTrackingStatus(race,'connected',18000),'Session ended');
 assert.match(liveTrackingStatus({...race,mode:'TEST'},'connected',10000),/historical/);
 assert.match(liveTrackingStatus({...race,upstream:'waiting-session'},'connected',10000),/Waiting/);
 assert.match(liveTrackingStatus({...race,upstream:'authentication-error'},'connected',10000),/authentication/);
 assert.match(liveTrackingStatus(race,'disconnected',10000),/disconnected/);
});
test('LIVE controls remain visible without TEST permission and send independent actions',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'});
 try{
  const {default:Controls}=await server.ssrLoadModule('/src/race/LiveControls.jsx');
  const markup=renderToStaticMarkup(createElement(Controls,{feed:{race:initialRaceState(),connection:'connected',controls:false,clockMs:10000,send:()=>{}}}));
  assert.match(markup,/Start LIVE/);assert.match(markup,/Stop LIVE/);assert.match(markup,/Discover race sessions/);assert.match(markup,/LIVE session/);
 }finally{await server.close();}
});
