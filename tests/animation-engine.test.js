import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AnimationEngine } from '../src/animation/engine.js';

function envelope(type,clockMs,sequence,extra={}){
  return {version:1,type,generation:1,sequence,mode:'TEST',playback:'playing',speed:1,clockMs,...extra};
}
function seed(engine,speed=1){
  engine.ingest(envelope('snapshot',1000,1,{speed,topics:{}}),0);
  engine.setBuffer(400);
  for(let time=0;time<=3000;time+=200)engine.add('1',{time,x:time/10,y:10});
}

test('continuous clock advances between packets without latest-sample re-anchoring',()=>{
  const e=new AnimationEngine();seed(e);
  const start=e.frame(0).get('1').point.x;
  let previous=start;
  for(let now=16;now<=500;now+=16){
    // Clock ticks + batched GPS arrivals, not one animation reset/sample.
    if(now===160)e.ingest(envelope('topic',500,2,{topic:'Position.z',data:{1:{_history:[{time:3200,x:320,y:10}]}}}),now);
    const x=e.frame(now).get('1').point.x;
    assert.ok(x>=previous && x-previous<=1.8,`jump at ${now}: ${x-previous}`);
    previous=x;
  }
  assert.ok(previous>start+40);
});
test('1x, 2x, 5x, 10x preserve source-time velocity and smooth frames',()=>{
  for(const speed of [1,2,5,10]){
    const e=new AnimationEngine();seed(e,speed);
    for(let time=3200;time<=10000;time+=200)e.add('1',{time,x:time/10,y:10});
    const x=e.frame(0).get('1').point.x;
    for(let now=10;now<=300;now+=10)e.frame(now);
    const end=e.lastFrame.get('1').point.x;
    assert.ok(Math.abs(end-x-30*speed)<0.01,`speed ${speed}: ${end-x}`);
  }
});
test('pause freezes immediately; resume preserves cursor and speed change does not rebase',()=>{
  const e=new AnimationEngine();seed(e);e.frame(0);e.frame(100);
  e.ingest(envelope('status',1100,2,{playback:'paused'}),100);
  const frozen=e.frame(116).get('1').point.x;
  assert.equal(e.frame(900).get('1').point.x,frozen);
  e.ingest(envelope('status',1100,3),900);
  assert.equal(e.frame(900).get('1').point.x,frozen);
  assert.ok(e.frame(916).get('1').point.x>frozen);
  const before=e.cursor;
  e.ingest(envelope('status',1116,4,{speed:5}),916);
  e.frame(916);assert.equal(e.cursor,before);
});
test('batched, duplicate and late samples are retained in sorted source-time order',()=>{
  const e=new AnimationEngine();e.ingest(envelope('snapshot',1000,1,{topics:{}}),0);
  e.ingest(envelope('topic',300,2,{topic:'Position.z',data:{7:{_history:[{time:600,x:60,y:1},{time:200,x:20,y:1},{time:400,x:40,y:1}]}}}),10);
  e.ingest(envelope('topic',700,3,{topic:'Position.z',data:{7:{_history:[{time:300,x:30,y:1},{time:400,x:40,y:1}]}}}),20);
  assert.deepEqual(e.drivers.get('7').samples.map(p=>p.time),[200,300,400,600]);
  assert.equal(e.drivers.get('7').duplicates,1);
});
test('missing samples hide gap/recovery; underruns hold but never extrapolate indefinitely',()=>{
  const e=new AnimationEngine();
  e.add('1',{time:100,x:10,y:1});e.add('1',{time:300,x:30,y:1});e.add('1',{time:3000,x:300,y:1});
  assert.equal(e.evaluate(e.drivers.get('1'),500,3100).state,'recovering');
  assert.equal(e.evaluate(e.drivers.get('1'),500,3100).point,null);
  assert.equal(e.evaluate(e.drivers.get('1'),3100,3100).state,'recovering');
  assert.equal(e.evaluate(e.drivers.get('1'),6000,6000).state,'stale');
  e.add('1',{time:3200,x:320,y:1});
  assert.equal(e.evaluate(e.drivers.get('1'),3100,3200).state,'interpolating');
});
test('invalid/spike rejection, adaptive cadence buffer, and stable identity across updates',()=>{
  const e=new AnimationEngine();
  e.add('44',{time:100,x:10,y:1});e.add('44',{time:400,x:40,y:1});e.add('44',{time:1100,x:110,y:1});
  e.add('44',{time:1200,x:NaN,y:1});e.add('44',{time:1300,x:10000,y:1});
  assert.equal(e.drivers.get('44').rejected,2);
  assert.ok(e.bufferMs()>=600);
  const samples=e.drivers.get('44').samples;
  e.configure({maxGapMs:1600});assert.equal(e.drivers.get('44').samples,samples);
  e.setBuffer(900);assert.equal(e.bufferMs(),900);e.setBuffer(null);
  assert.ok(e.bufferMs()!==900);
});
test('clip restart/switch clears old buffers and clocks; subscriptions survive control updates',()=>{
  const e=new AnimationEngine();seed(e);let count=0;
  const unsubscribe=e.subscribe('1',()=>count++);
  e.frame(0);e.frame(16);assert.ok(count>=3);
  e.ingest(envelope('snapshot',100,1,{generation:2,topics:{}}),16);
  assert.equal(e.drivers.size,0);assert.equal(e.cursor,null);
  e.ingest(envelope('topic',2000,99,{generation:1,topic:'Position.z',data:{1:{X:10,Y:1,_sampleTimeMs:2000}}}),20);
  assert.equal(e.drivers.size,0);
  unsubscribe();assert.equal(e.listeners.size,0);
});
test('irregular cadence and control-clock jitter never rewind the presentation clock',()=>{
  const e=new AnimationEngine();seed(e);
  let cursor=-Infinity;
  for(let now=0;now<1000;now+=16){
    if(now%80===0)e.ingest(envelope('clock',1000+now+(now%160===0?-30:30),2+now),now);
    e.frame(now);assert.ok(e.cursor>=cursor);cursor=e.cursor;
  }
});

test('regression: newest sample cannot jump the cursor at the same animation timestamp',()=>{
  const legacyTarget=(clock,latest)=>clock-Math.max(250,clock-latest+250);
  assert.equal(legacyTarget(1000,1100)-legacyTarget(1000,900),100);
  const e=new AnimationEngine();seed(e);e.frame(100);
  const cursor=e.cursor;
  e.ingest(envelope('topic',900,2,{topic:'Position.z',data:{1:{_history:[{time:3200,x:320,y:10}]}}}),100);
  e.frame(100);assert.equal(e.cursor,cursor);
});
test('all 22 driver subscriptions remain stable while timing updates reorder standings',()=>{
  const e=new AnimationEngine();e.ingest(envelope('snapshot',1000,1,{topics:{}}),0);e.setBuffer(400);
  const subscriptions=[];
  for(let number=1;number<=22;number++){
    e.add(String(number),{time:500,x:number*10,y:1});e.add(String(number),{time:1500,x:number*10+100,y:1});
    subscriptions.push(e.subscribe(String(number),()=>{}));
  }
  e.frame(0);const before=e.lastFrame.get('22').point.x;
  e.ingest(envelope('topic',1,2,{topic:'TimingData',data:{22:{Position:'1'},1:{Position:'22'}}}),0);
  e.frame(16);assert.equal(e.listeners.size,22);assert.ok(e.lastFrame.get('22').point.x>before);
  subscriptions.forEach(stop=>stop());assert.equal(e.listeners.size,0);
});

test('streaming batches at all TEST speeds retain intermediate positions and adapt to delivery span',()=>{
  for(const speed of [1,2,5,10]){
    const e=new AnimationEngine();let sequence=1,nextSample=1000;let history=[];
    e.ingest(envelope('snapshot',1000,sequence++,{speed,topics:{}}),0);
    let previous=null,intermediate=0;
    for(let wall=0;wall<=3000;wall+=16){
      const source=1000+wall*speed;
      if(wall%80===0){
        while(nextSample<=source){history.push({time:nextSample,x:nextSample/10,y:1});nextSample+=nextSample%400===0?150:250;}
        history=history.slice(-128);
        e.ingest(envelope('topic',source-250,sequence++,{speed,topic:'Position.z',data:{1:{_history:history}}}),wall);
        e.ingest(envelope('clock',source,sequence++,{speed}),wall);
      }
      const output=e.frame(wall).get('1');
      if(output?.state==='interpolating'){
        intermediate++;
        if(previous!==null){assert.ok(output.point.x>=previous);assert.ok(output.point.x-previous<=16*speed/10*1.11+0.001);}
        previous=output.point.x;
      }else previous=null;
    }
    assert.ok(intermediate>70,`too few interpolated frames at ${speed}x: ${intermediate}`);
    assert.ok(e.bufferMs()>=80*speed,'delivery span not covered');
  }
});
test('background suspension hides before reacquiring; never runs a catch-up shortcut',()=>{
  const e=new AnimationEngine();seed(e);let output;
  e.subscribe('1',value=>{output=value;});e.frame(0);e.frame(16);e.frame(2000);
  assert.equal(output.state,'recovering');assert.equal(output.point,null);assert.equal(e.cursor,null);
});
