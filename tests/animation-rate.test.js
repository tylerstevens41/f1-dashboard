// Synthetic clock/trajectory regression fixtures; no visual real-race claim.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AnimationEngine } from '../src/animation/engine.js';
function packet(type,time,sequence,extra={}){return {version:1,type,clockMs:time,generation:1,sequence,mode:'TEST',speed:1,playback:'playing',...extra};}
function trajectory(e,base=1000000){
  let t=base-2000,index=0;
  while(t<base+20000){e.add('1',{time:t,x:(t-base)/10,y:100});t+=[130,270,190,410][index++%4];}
}

test('manual 1000 ms: packet timing corrections cannot pulse constant source speed at any playback rate',()=>{
  for(const speed of [1,2,5,10]){
    const e=new AnimationEngine();e.ingest(packet('snapshot',1000000,1,{speed,topics:{}}),0);
    e.setBuffer(1000);e.setTracing(true);trajectory(e);
    let seq=2;
    for(let wall=0;wall<=1500;wall+=10){
      if(wall%50===0){const late=[0,30,5,45,10][(wall/50)%5];
        e.ingest(packet('clock',1000000+(wall-late)*speed,seq++,{speed,transportMs:wall-late}),wall);}
      e.frame(wall);
    }
    assert.ok(e.trace.length>100);
    for(const row of e.trace){
      assert.ok(Math.abs(row.presentationRate-speed)<1e-8);
      assert.ok(Math.abs(row.renderedPathSpeed-100)<1e-7);
      assert.ok(Math.abs(row.sourcePathSpeed-100)<1e-7);
    }
    assert.equal(e.clock.rate,speed);assert.equal(e.rebuffers,0);
  }
});
test('automatic recommendation changes do not continuously alter locked delay or presentation speed',()=>{
  const e=new AnimationEngine();e.ingest(packet('snapshot',1000000,1,{topics:{}}),0);trajectory(e);e.setTracing(true);
  e.frame(0);const locked=e.targetDelay;
  for(let wall=10;wall<=2000;wall+=10){
    e.jitter=[wall%200<100?20:1400];e.deliveryIntervals=[wall%200<100?80:400];
    e.frame(wall);
  }
  assert.equal(e.targetDelay,locked);assert.equal(e.rebuffers,0);
  assert.ok(e.trace.every(row=>Math.abs(row.presentationRate-1)<1e-10));
  assert.ok(new Set(e.trace.map(row=>row.recommendedBufferMs)).size>1);
});
test('LIVE packet jitter stays nominal; only sustained drift gets a bounded slow correction',()=>{
  const e=new AnimationEngine();e.ingest(packet('snapshot',1000000,1,{mode:'LIVE',topics:{}}),0);
  for(let wall=1000;wall<=29000;wall+=1000){e.ingest(packet('status',1000000+wall+(wall%2000?25:-25),2+wall,{mode:'LIVE'}),wall);assert.equal(e.clock.rate,1);}
  let previousRate=e.clock.rate,lastChange=0;
  for(let wall=30000;wall<=125000;wall+=1000){
    e.ingest(packet('status',1000000+wall+200,2+wall,{mode:'LIVE'}),wall);
    assert.ok(Math.abs(e.clock.rate-1)<=0.001000001);
    if(previousRate!==e.clock.rate){assert.ok(wall-lastChange>=30000);lastChange=wall;previousRate=e.clock.rate;}
  }
});
test('pause/resume/restart keep phase changes separate from rendered velocity',()=>{
  const e=new AnimationEngine();e.ingest(packet('snapshot',1000000,1,{topics:{}}),0);trajectory(e);e.setBuffer(1000);e.setTracing(true);
  e.frame(0);e.frame(100);const before=e.cursor;
  e.ingest(packet('status',1000100,2,{playback:'paused'}),100);e.frame(500);assert.equal(e.cursor,before);
  e.ingest(packet('status',1000100,3),500);e.frame(500);assert.equal(e.cursor,before);
  e.frame(510);assert.equal(e.cursor-before,10);
  e.ingest(packet('snapshot',1000000,1,{generation:2,topics:{}}),510);
  assert.equal(e.cursor,null);assert.equal(e.trace.length,0);assert.equal(e.drivers.size,0);
});
test('trace distinguishes GPS quantization and corner chord effects from clock-rate errors',()=>{
  const e=new AnimationEngine();e.ingest(packet('snapshot',900,1,{topics:{}}),0);e.setBuffer(500);e.setTracing(true);
  for(const p of [{time:0,x:0,y:10},{time:500,x:50,y:10},{time:1000,x:50,y:60},{time:1500,x:50,y:60},{time:2000,x:100,y:60}])e.add('1',p);
  for(let wall=0;wall<=1100;wall+=30)e.frame(wall);
  assert.ok(e.trace.some(row=>row.repeated));
  assert.ok(e.trace.some(row=>row.renderedChordSpeed+0.01<row.renderedPathSpeed));
  assert.ok(e.trace.every(row=>Math.abs(row.presentationRate-1)<1e-9));
  assert.match(e.traceCsv(),/phaseErrorMs/);assert.match(e.traceCsv(),/sourceIntervalMs/);
});
