import { test } from 'node:test';
import assert from 'node:assert/strict';
import { interpolateSamples, appendSample } from '../src/circuits/interpolation.js';
import { validateCalibration, calibrationGeometry } from '../src/circuits/calibration.js';

function calibration(){return {schema:'livef1-circuit-calibration-v1',source:'LiveF1',circuitId:'unit',layoutVersion:'v1',status:'candidate',geometry:{points:Array.from({length:65},(_,i)=>({x:100+50*Math.cos(i/64*Math.PI*2),y:100+30*Math.sin(i/64*Math.PI*2)}))},mapping:{matrix:[2,0,0,2,10,20]},validation:{verified:false},provenance:{synthetic:true}};}

test('calibration persists and maps only car coordinates, not geometry twice',()=>{
  const data=validateCalibration(JSON.parse(JSON.stringify(calibration())),'unit');
  const geometry=calibrationGeometry(data,[]);
  assert.deepEqual(geometry.project(20,30),geometry.projectNative(50,80));
  assert.throws(()=>validateCalibration({...data,status:'verified'},'unit'));
  assert.throws(()=>validateCalibration(data,'austin'));
  assert.throws(()=>validateCalibration({...data,mapping:{matrix:[0,0,0,0,0,0]}},'unit'));
});
test('interpolation uses timestamps and never extrapolates beyond last measured point',()=>{
  const points=[{time:1000,x:10,y:10},{time:1200,x:30,y:20}];
  assert.deepEqual(interpolateSamples(points,1100),{x:20,y:15,held:false});
  assert.deepEqual(interpolateSamples(points,1500),{x:30,y:20,held:true});
  assert.equal(interpolateSamples(points,5000),null);
  assert.equal(interpolateSamples(points,999),null);
});
test('invalid GPS, out-of-order updates and spikes cannot teleport cars',()=>{
  const original=[{time:1000,x:10,y:10}];
  assert.equal(appendSample(original,{time:1100,x:NaN,y:10}),original);
  assert.equal(appendSample(original,{time:900,x:20,y:10}),original);
  assert.equal(appendSample(original,{time:1100,x:10000,y:10}),original);
  const recovered=appendSample(original,{time:3000,x:10000,y:10});
  assert.equal(recovered.length,1);
  assert.equal(interpolateSamples([...original,{time:4000,x:100,y:10}],2500).held,true);
  assert.equal(interpolateSamples([{time:1000,x:10,y:10},{time:1100,x:10000,y:10}],1050),null);
});
