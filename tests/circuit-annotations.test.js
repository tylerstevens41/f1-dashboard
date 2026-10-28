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

test('calculated boundaries load without replacing reviewed positions, corners, or manual overrides',async()=>{
 const {mergeImportedCorners,placeAnnotation}=await import('../src/circuits/annotations.js');
 const calculated=at=>({at,status:'provisional',calculated:true,sourceEstimate:{at,statistics:{p95LapFraction:.001}}});
 const base={...emptyAnnotations(circuit,geometry),startFinish:calculated(.8),sector1End:calculated(.05),sector2End:calculated(.5),boundaryDiagnostics:{validLaps:7},direction:-1};
 const existing={...emptyAnnotations(circuit,geometry),corners:[{number:1,at:.2,status:'provisional'}]};
 const merged=mergeImportedCorners(base,existing);
 assert.equal(merged.startFinish.at,.8);assert.equal(merged.corners.length,1);assert.equal(merged.direction,-1);
 const reviewed=mergeImportedCorners(base,{startFinish:{at:.75,status:'verified'}});
 assert.equal(reviewed.startFinish.at,.75);assert.equal(reviewed.startFinish.sourceEstimate.at,.8);
 const chosen=mergeImportedCorners(reviewed,{startFinish:{...reviewed.startFinish,status:'provisional',manualOverride:false,preferCalculated:true,previousOverride:{at:.75}}});
 assert.equal(chosen.startFinish.at,.8);assert.equal(chosen.startFinish.previousOverride.at,.75);
 const adjusted=placeAnnotation(merged,{kind:'sector1End'},.07);
 assert.equal(adjusted.sector1End.at,.07);assert.equal(adjusted.sector1End.sourceEstimate.at,.05);
 assert.equal(mergeImportedCorners(base,adjusted).sector1End.at,.07);
 const cleared=mergeImportedCorners(base,{sector1End:null,boundaryOverrides:{sector1End:true}});
 assert.equal(cleared.sector1End,null);
});

test('reported Austin fractions can differ from displayed manual estimates; preview is nondestructive',async()=>{
 const {boundaryDisplayAudit,calculatedBoundaryPreview}=await import('../src/circuits/boundaryAudit.js');
 const {mergeImportedCorners}=await import('../src/circuits/annotations.js');
 const mark=at=>({at,status:'provisional',calculated:true,sourceEstimate:{at}});
 const source={...emptyAnnotations(circuit,geometry),startFinish:mark(.9962572732649239),sector1End:mark(.29711217736772716),sector2End:mark(.708877719002983)};
 // This reproduces a possible older FIA-estimate override, not an assertion
 // that the user's browser contains these particular values.
 const manual={sector1End:{at:(source.startFinish.at+1914/5513)%1,status:'provisional'}};
 const effective=mergeImportedCorners(source,manual);
 const audit=boundaryDisplayAudit(effective,geometry,{sectorFile:source,annotationFile:manual});
 const s1=audit.find(r=>r.key==='sector1End');assert.equal(s1.origin,'manual-file');assert.equal(s1.different,true);
 assert.equal(s1.calculatedAt,source.sector1End.at);assert.equal(s1.displayedAt,manual.sector1End.at);
 const preview=calculatedBoundaryPreview(effective);
 assert.equal(preview.sector1End.at,source.sector1End.at);assert.equal(effective.sector1End.at,manual.sector1End.at);
});
