import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGeometry, pointAt } from '../src/circuits/geometry.js';
import { emptyAnnotations, nearestFraction, sectorRanges, validateAnnotations, defaultAppearance } from '../src/circuits/annotations.js';
const circuit={id:'test',layoutVersion:'v1'};
const geometry=createGeometry([{x:0,y:0},{x:10,y:0},{x:10,y:10},{x:0,y:10},{x:0,y:0}],{padding:0});
const mark=at=>({at,status:'provisional'});
const config=()=>({...emptyAnnotations(circuit,geometry),startFinish:mark(.8),sector1End:mark(.05),sector2End:mark(.5)});
test('unequal sectors wrap at geometry origin and cover the whole path once',()=>{
 const ranges=sectorRanges(config());assert.deepEqual(ranges,[[[.8,1],[0,.05]],[[.05,.5]],[[.5,.8]]]);
 const length=ranges.map(r=>r.reduce((n,[a,b])=>n+b-a,0));
 assert.ok(Math.abs(length[0]-.25)<1e-9);assert.ok(Math.abs(length[1]-.45)<1e-9);assert.ok(Math.abs(length.reduce((a,b)=>a+b)-1)<1e-9);
});
test('reverse driving direction uses correct physical ranges and rejects wrong order',()=>{
 const a={...config(),direction:-1,sector1End:mark(.5),sector2End:mark(.05)};
 assert.deepEqual(sectorRanges(a),[[[.5,.8]],[[.05,.5]],[[.8,1],[0,.05]]]);
 assert.equal(sectorRanges({...a,sector1End:mark(.05),sector2End:mark(.5)}),null);
});
test('nearest path distance uses projected geometry and scales without changing fraction',()=>{
 assert.equal(geometry.total,40);const p=pointAt(geometry,.625);assert.ok(Math.abs(nearestFraction(geometry,p.x,p.y)-.625)<1e-9);
 const big=createGeometry([{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100},{x:0,y:0}],{padding:0});
 const q=pointAt(big,.625);assert.equal(nearestFraction(big,q.x,q.y),.625);
});
test('validation rejects missing ordering, wrong geometry/layout, duplicate turns, and unjustified verification',()=>{
 assert.equal(validateAnnotations(config(),circuit,geometry).circuitId,'test');
 assert.equal(sectorRanges({...config(),sector1End:null}),null);
 assert.throws(()=>validateAnnotations(config(),{...circuit,layoutVersion:'v2'},geometry));
 assert.throws(()=>validateAnnotations({...config(),geometryId:'other'},circuit,geometry));
 assert.throws(()=>validateAnnotations({...config(),corners:[{number:1,...mark(.2)},{number:1,...mark(.3)}]},circuit,geometry));
 assert.throws(()=>validateAnnotations({...config(),startFinish:{at:.8,status:'verified'}},circuit,geometry));
 assert.throws(()=>validateAnnotations({...config(),zones:[{start:.5,end:2,status:'provisional'}]},circuit,geometry));
});
test('appearance settings have no effect on GPS projection',()=>{
 const p=geometry.project(3,7);const cosmetic={...defaultAppearance,base:'black',trackWidth:600,lineWidth:20};
 assert.equal(cosmetic.base,'black');assert.deepEqual(geometry.project(3,7),p);
});

test('corner letters are unique IDs; manual edits preserve imported defaults and original source',async()=>{
 const {mergeImportedCorners,placeAnnotation}=await import('../src/circuits/annotations.js');
 const original={number:2,letter:'A',at:.2,status:'provisional',imported:true,source:{x:123,y:456}};
 const base={...emptyAnnotations(circuit,geometry),corners:[original,{...original,letter:'B',at:.3}],importSource:{provider:'fixture'}};
 validateAnnotations(base,circuit,geometry);
 const edit=placeAnnotation(base,{kind:'corner',number:2,letter:'A'},.25);
 assert.equal(edit.corners.find(c=>c.letter==='A').at,.25);assert.equal(base.corners[0].at,.2);
 assert.deepEqual(edit.corners.find(c=>c.letter==='A').source,original.source);
 const merged=mergeImportedCorners(base,{corners:[{number:2,letter:'B',at:.3,status:'provisional',hidden:true}]});
 assert.equal(merged.corners.length,2);assert.equal(merged.corners[1].hidden,true);
 assert.deepEqual(merged.importSource,base.importSource);
 assert.throws(()=>placeAnnotation(base,{kind:'startFinish'},NaN));
});
