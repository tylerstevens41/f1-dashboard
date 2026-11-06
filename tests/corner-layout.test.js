import {test} from 'node:test';
import assert from 'node:assert/strict';
import {layoutCornerLabels,cornerFrame,segmentDistance} from '../src/circuits/cornerLayout.js';
const geometry={points:[{x:0,y:0},{x:2000,y:0}],lengths:[0,2000],total:2000};
const label=(number,x=1000,y=-150,at=x/2000)=>({feature:{number,at,offset:{x:0,y:-150}},x,y,radius:40});
const layout=(labels,extra={})=>layoutCornerLabels({labels,geometry,padding:10,trackWidth:20,...extra});
const byNumber=(result,n)=>result.labels.find(l=>l.feature.number===n);
test('higher number flips first at the exact local tangent preserving distance',()=>{
 const input=[label(17,1010),label(15)];const result=layout(input);
 assert.equal(byNumber(result,15).strategy,'preferred');assert.equal(byNumber(result,17).strategy,'flipped');
 assert.equal(byNumber(result,17).y,150);assert.equal(byNumber(result,17).x,1010);assert.deepEqual(result.warnings,[]);
 assert.equal(input[0].y,-150);
});
test('all labels checked: flip into a third label requires a bounded alternate',()=>{
 const result=layout([label(15),label(17,1010),label(18,1010,150)]);
 assert.equal(byNumber(result,15).strategy,'preferred');assert.equal(byNumber(result,17).strategy,'alternate');
 assert.deepEqual(result.warnings,[]);
});
test('multiple collisions settle deterministically regardless of input order',()=>{
 const labels=[label(17,1010),label(15),label(16,1020),label(18,1030)];
 assert.deepEqual(layout(labels),layout([...labels].reverse()));
 assert.equal(byNumber(layout(labels),15).strategy,'preferred');
});
test('noncolliding manual offsets remain exact and no registry data mutate',()=>{
 const labels=[label(1,200,-300),label(2,1800,-220)];const copy=JSON.stringify(labels);
 const result=layout(labels);assert.ok(result.labels.every(l=>l.strategy==='preferred'));
 assert.equal(JSON.stringify(labels),copy);assert.equal(result.labels[0].y,-300);
});
test('local tangent reflects a vertical-track label horizontally',()=>{
 const vertical={points:[{x:0,y:0},{x:0,y:2000}],lengths:[0,2000],total:2000};
 const labels=[label(1,-150,1000,.5),label(2,-150,1010,.505)];
 const result=layout(labels,{geometry:vertical});assert.ok(Math.abs(byNumber(result,2).x-150)<1e-8);
 const frame=cornerFrame(vertical,.5);assert.ok(Math.abs(frame.normal.x+1)<1e-10);
});
test('hairpin and neighboring track segments block an unsafe opposite-side flip',()=>{
 const hairpin={points:[{x:0,y:0},{x:2000,y:0},{x:2000,y:180},{x:0,y:180}],lengths:[0,2000,2180,4180],total:4180};
 const result=layout([label(15,1000,-150,1000/4180),label(17,1010,-150,1010/4180)],{geometry:hairpin});
 assert.notEqual(byNumber(result,17).strategy,'flipped');
 assert.deepEqual(result.warnings,[]);
});
test('SVG uniform scaling preserves placement and size changes recalculate collisions',()=>{
 const labels=[label(1,900),label(2,1000)];assert.equal(byNumber(layout(labels),2).strategy,'preferred');
 const larger=layout(labels.map(l=>({...l,radius:70})));assert.notEqual(byNumber(larger,2).strategy,'preferred');
 const factor=2,scaledGeometry={...geometry,points:geometry.points.map(p=>({x:p.x*factor,y:p.y*factor})),lengths:geometry.lengths.map(v=>v*factor),total:geometry.total*factor};
 // Stroke-outline safety inset is 20 SVG units; use ample clearances here.
 const scaled=layout(labels.map(l=>({...l,x:l.x*factor,y:l.y*factor,radius:l.radius*factor})),{geometry:scaledGeometry,padding:20,trackWidth:40});
 assert.equal(scaled.labels[1].x,2000);assert.equal(scaled.labels[1].strategy,'preferred');
});
test('fixed annotation avoidance and impossible cases produce deterministic warnings',()=>{
 const result=layout([label(1)],{obstacles:[{x:1000,y:-150,radius:50}]});assert.notEqual(result.labels[0].strategy,'preferred');
 const impossible=layout([label(1)],{obstacles:[{x:1000,y:0,radius:10000}]});
 assert.equal(impossible.warnings.length,1);assert.deepEqual(impossible,layout([label(1)],{obstacles:[{x:1000,y:0,radius:10000}]}));
 assert.ok(Math.hypot(impossible.labels[0].x-1000,impossible.labels[0].y)<400);
});
test('corner letters use numeric turn priority then stable suffix ordering',()=>{
 const a=label(2),b={...label(2,1010),feature:{...label(2,1010).feature,letter:'A'}};
 assert.deepEqual(layout([b,a]),layout([a,b]));assert.equal(layout([b,a]).labels[0].feature.letter,undefined);
 assert.equal(segmentDistance({x:4,y:3},{x:0,y:0},{x:8,y:0}),3);
});
test('figure-eight crossover keeps distinct path visits and stable label anchors',async()=>{
 const {pointAt,pathRange}=await import('../src/circuits/geometry.js');
 const points=Array.from({length:257},(_,i)=>{const t=i/256*2*Math.PI;return {x:5000*Math.sin(t),y:2500*Math.sin(2*t)};});
 const lengths=[0];for(let i=1;i<points.length;i++)lengths.push(lengths.at(-1)+Math.hypot(points[i].x-points[i-1].x,points[i].y-points[i-1].y));
 const eight={points,lengths,total:lengths.at(-1)};
 const first=pointAt(eight,0),second=pointAt(eight,.5);
 assert.ok(Math.hypot(first.x-second.x,first.y-second.y)<1e-8);
 assert.notEqual(first.angle,second.angle);
 assert.ok(pathRange(eight,0,.5).split('L').length>100);
 const input=[{feature:{number:15,at:0},x:0,y:-700,radius:255},{feature:{number:17,at:.5},x:0,y:-700,radius:255}];
 const result=layout(input,{geometry:eight,trackWidth:330});
 assert.deepEqual(result,layout([...input].reverse(),{geometry:eight,trackWidth:330}));
 assert.equal(result.labels[0].feature.at,0);assert.equal(result.labels[1].feature.at,.5);
 assert.deepEqual(input.map(l=>l.y),[-700,-700]);
});
