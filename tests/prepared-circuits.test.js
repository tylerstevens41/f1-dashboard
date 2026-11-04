import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validatePrepared,preparedForSession,preparedCircuit,gpsCompatibility} from '../src/circuits/prepared.js';
import {calibrationGeometry} from '../src/circuits/calibration.js';
import {geometryId,emptyAnnotations,resolveBoundarySources} from '../src/circuits/annotations.js';
import {raceReducer,initialRaceState,selectCircuit} from '../src/race/state.js';
import {AnimationEngine} from '../src/animation/engine.js';
const session={StartDate:'2026-10-30T12:00:00Z',Meeting:{Circuit:{Key:65,ShortName:'Mexico City'}}};
function fixture(){
 const points=Array.from({length:65},(_,i)=>({x:10000*Math.cos(i/64*Math.PI*2),y:6000*Math.sin(i/64*Math.PI*2)}));points[64]={...points[0]};
 const calibration={schema:'livef1-circuit-calibration-v1',circuitId:'mexico-city',layoutVersion:'mexico-city-2026-livef1-v1',source:'LiveF1',status:'candidate',geometry:{points},mapping:{matrix:[1,0,0,1,0,0]},validation:{automaticChecksPassed:true,verified:false},provenance:{synthetic:false,testFixture:true}};
 return {schema:'prepared-circuit-v1',toolVersion:1,identity:{id:'mexico-city',name:'Mexico City',circuitKey:'65',year:2026,layoutVersion:calibration.layoutVersion,assetKey:'circuit-65-2026'},calibration,geometryId:geometryId(calibrationGeometry(calibration)),corners:null,sectors:null};
}
test('dynamic session matching uses stable circuit key and season, not event name guesses',()=>{
 const b=validatePrepared(fixture());assert.equal(preparedForSession({x:b},session),b);
 assert.equal(preparedForSession({x:b},{...session,StartDate:'2025-01-01'}),null);
 assert.equal(preparedForSession({x:b},{...session,Meeting:{Circuit:{Key:999}}}),null);
 assert.equal(selectCircuit({Meeting:{Circuit:{ShortName:'Austin'}}}),'Austin');
});
test('new assets become selectable without registry mutation or frontend restart',()=>{
 const bundles={};assert.equal(preparedForSession(bundles,session),null);
 const b=fixture();bundles[b.identity.assetKey]=validatePrepared(JSON.parse(JSON.stringify(b)));
 const selected=preparedForSession(bundles,session);assert.equal(preparedCircuit(selected).name,'Mexico City');
 assert.equal(preparedCircuit(selected).motion.maxGapMs,1500);
});
test('reject geometry, annotation layout and failed validation mismatches',()=>{
 const b=fixture();b.geometryId='incorrect';assert.throws(()=>validatePrepared(b));
 const c=fixture();c.calibration.validation.automaticChecksPassed=false;assert.throws(()=>validatePrepared(c));
 const d=fixture();d.corners={...emptyAnnotations(preparedCircuit(d),calibrationGeometry(d.calibration)),layoutVersion:'other'};assert.throws(()=>validatePrepared(d));
});
test('live/test compatibility uses fresh measured GPS and blocks shifted coordinates without snapping',()=>{
 const b=fixture(),geometry=calibrationGeometry(b.calibration);
 const drivers=b.calibration.geometry.points.slice(0,8).map(p=>({gps:{X:p.x,Y:p.y,_sampleTimeMs:1000,Status:'OnTrack'}}));
 assert.equal(gpsCompatibility(geometry,drivers,1000).status,'compatible-sample');
 const shifted=drivers.map(d=>({gps:{...d.gps,X:d.gps.X+100000}}));
 assert.equal(gpsCompatibility(geometry,shifted,1000).status,'incompatible');
 assert.equal(gpsCompatibility(geometry,drivers,5000).status,'waiting-for-gps');
 assert.equal(gpsCompatibility(geometry,drivers.slice(0,1),1000).status,'waiting-for-gps');
 assert.equal(drivers[0].gps.X,10000);
});
test('preparation events cannot reset race state or animation samples; calculated default preserved',()=>{
 const state=initialRaceState(),engine=new AnimationEngine();
 const event={version:1,type:'circuit-assets',bundle:fixture()};
 assert.equal(raceReducer(state,event),state);const before=engine.generation;engine.ingest(event,100);assert.equal(engine.generation,before);
 const b=fixture(),geometry=calibrationGeometry(b.calibration),base=emptyAnnotations(preparedCircuit(b),geometry);
 const calculated={...base,startFinish:{at:.99,status:'provisional',calculated:true},sector1End:{at:.2,status:'provisional',calculated:true},sector2End:{at:.75,status:'provisional',calculated:true}};
 assert.equal(resolveBoundarySources({...base,sector1End:{at:.33,status:'verified'}},calculated).sector1End.at,.2);
});

test('preparation diagnostics show exception stages and lap counts in the development panel',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'});
 try{
  const {default:Panel}=await server.ssrLoadModule('/src/circuits/PreparationPanel.jsx');
  const job={state:'failed',identity:{name:'Mexico City',year:2026},windowDiagnostics:[{offset:5400,status:'error',stage:'extract',archiveRetrieved:true,eventCount:120,positionMessages:50,decodedPositionRecords:400,driversRepresented:20,candidateLaps:null,acceptedCompleteLaps:null,calibrationAttempted:false,error:{exceptionType:'KeyError',stage:'extract',hint:'Inspect decoder/schema',location:{file:'calibrate.py',line:60,function:'collect_clip'}}},{offset:6000,status:'rejected',stage:'clean',archiveRetrieved:true,candidateLaps:10,acceptedCompleteLaps:2,reason:'insufficient-complete-laps',rejected:{incompleteLaps:8}}]};
  const markup=renderToStaticMarkup(createElement(Panel,{job,onPrepare:()=>{}}));
  assert.match(markup,/Window 5400s/);assert.match(markup,/KeyError/);assert.match(markup,/calibrate.py:60/);
  assert.match(markup,/Candidate laps 10/);assert.match(markup,/complete accepted 2/);assert.match(markup,/insufficient-complete-laps/);
 }finally{await server.close();}
});
