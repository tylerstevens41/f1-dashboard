import {test} from 'node:test';
import assert from 'node:assert/strict';
import {CompatibilityTracker} from '../src/circuits/compatibilityTracker.js';
import {gpsCompatibility} from '../src/circuits/prepared.js';
import {AnimationEngine} from '../src/animation/engine.js';
const geometry={points:[{x:0,y:0},{x:10000,y:0}],width:11300,height:2300,project:(x,y)=>({x,y})};
const drivers=(time,count=6,offset=0)=>Array.from({length:count},(_,i)=>({driver_number:String(i+1),gps:{X:1000+i*100,Y:offset,_sampleTimeMs:time,Status:'OnTrack'}}));
test('old global gate repeatedly loses quorum; session tracker preserves measured alignment',()=>{
 const tracker=new CompatibilityTracker();
 assert.equal(gpsCompatibility(geometry,drivers(1000),4000).status,'waiting-for-gps');
 const result=tracker.update(geometry,drivers(1000),4000);assert.equal(result.allowed,true);
 for(const time of [5000,6000,10000,32000])assert.equal(tracker.update(geometry,drivers(1000),time).allowed,true);
 assert.equal(tracker.lastSuccess,4000); // never fabricate a new success while no samples arrive
});
test('asynchronous drivers accumulate a quorum without requiring simultaneous updates',()=>{
 const tracker=new CompatibilityTracker();
 for(let i=1;i<=5;i++){
  const input=[{driver_number:String(i),gps:{X:i*100,Y:0,_sampleTimeMs:i*3000,Status:'OnTrack'}}];
  assert.equal(tracker.update(geometry,input,i*3000).allowed,i===5);
 }
});
test('incompatible new quorum blocks all markers; isolated bad driver remains blocked',()=>{
 const tracker=new CompatibilityTracker();tracker.update(geometry,drivers(1000),1000);
 const bad=tracker.update(geometry,drivers(2000,6,5000),2000);
 assert.equal(bad.allowed,false);assert.equal(bad.status,'incompatible');assert.equal(bad.blockedDrivers.length,6);
 assert.equal(tracker.update(geometry,drivers(3000),3000).allowed,true);
});
test('new session/reconnect tracker never reuses previous-session evidence',()=>{
 const previous=new CompatibilityTracker();previous.update(geometry,drivers(1000),1000);
 const next=new CompatibilityTracker();assert.equal(next.update(geometry,drivers(1000,1),1000).allowed,false);
 assert.equal(next.update(geometry,drivers(1000,6),40000).allowed,false);
 assert.equal(next.update(geometry,drivers(50000),40000).allowed,false);
});
test('LIVE stale check credits bounded presentation delay, TEST remains unchanged',()=>{
 const e=new AnimationEngine();e.add('1',{x:100,y:0,time:6000});e.add('1',{x:110,y:0,time:6500});
 const driver=e.drivers.get('1');
 assert.equal(e.evaluate(driver,6250,10000).state,'interpolating'); // 3.5s UTC age, valid delayed bracket
 e.mode='TEST';assert.equal(e.evaluate(driver,6250,10000).state,'stale');
 e.mode='LIVE';assert.equal(e.evaluate(driver,15000,20000).state,'stale');
 assert.equal(e.evaluate(driver,6250,20000).state,'stale'); // cannot hide unlimited wall-clock age with a stuck cursor
});
test('drivers expire independently and real data resumes without fabricated samples',()=>{
 const e=new AnimationEngine();
 for(const [id,t] of [['1',6000],['2',2000]]){e.add(id,{x:100,y:1,time:t});e.add(id,{x:110,y:1,time:t+500});}
 assert.ok(e.evaluate(e.drivers.get('1'),6250,10000).point);
 assert.equal(e.evaluate(e.drivers.get('2'),6250,10000).point,null);
 e.add('2',{x:120,y:1,time:6000});e.add('2',{x:130,y:1,time:6500});
 assert.ok(e.evaluate(e.drivers.get('2'),6250,10000).point);
});
test('continuous LIVE frames survive delayed one-second bursts and later expire honestly',()=>{
 const e=new AnimationEngine();e.ingest({version:1,type:'snapshot',generation:1,sequence:1,mode:'LIVE',clockMs:10000,topics:{}},0);e.setBuffer(4000);
 let newest=4750;
 const addUntil=end=>{while(newest<end){newest+=250;e.add('1',{time:newest,x:newest/10,y:1});}};
 addUntil(7000);
 for(let wall=0;wall<=4000;wall+=20){
  if(wall&&wall%1000===0)addUntil(7000+wall);
  const output=e.frame(wall).get('1');
  assert.equal(output.state,'interpolating');assert.ok(output.point);
 }
 for(let wall=4020;wall<=12000;wall+=20)e.frame(wall);
 assert.equal(e.lastFrame.get('1').state,'stale');assert.equal(e.lastFrame.get('1').point,null);
});
