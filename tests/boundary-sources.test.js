import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createGeometry} from '../src/circuits/geometry.js';
import {emptyAnnotations,mergeImportedCorners,resolveBoundarySources,chooseBoundarySource,editManualBoundary,placeAnnotation,validateAnnotations} from '../src/circuits/annotations.js';
import {calculatedBoundaryPreview,boundaryDisplayAudit} from '../src/circuits/boundaryAudit.js';
const circuit={id:'test',layoutVersion:'v1'};
const geometry=createGeometry([{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100},{x:0,y:0}]);
const mark=at=>({at,status:'provisional',calculated:true,sourceEstimate:{at,statistics:{p95LapFraction:.001}}});
const calc=()=>({...emptyAnnotations(circuit,geometry),startFinish:mark(.996),sector1End:mark(.297),sector2End:mark(.709),direction:1,boundaryDiagnostics:{accuracy:{status:'unverified'},fia:{warnings:['preserve warning']}},provenance:'calculation'});
const legacy=()=>({...emptyAnnotations(circuit,geometry),startFinish:{at:.99,status:'verified'},sector1End:{at:.35,status:'verified',manualOverride:true},sector2End:{at:.69,status:'provisional'},provenance:'independent review'});
const setup=()=>{const calculated=calc();return {calculated,value:resolveBoundarySources(mergeImportedCorners(calculated,legacy()),calculated)};};

test('calculation is default over legacy manual flags, reviewed records and browser drafts',()=>{
 const {calculated,value}=setup();
 for(const key of ['startFinish','sector1End','sector2End']){
  assert.equal(value[key].at,calculated[key].at);assert.equal(value.boundaryEffectiveSources[key],'calculated');
  assert.equal(value.boundaryManualPositions[key].at,legacy()[key].at);
 }
 assert.equal(value.sector1End.status,'provisional');assert.equal(value.boundaryManualPositions.sector1End.status,'verified');
 assert.equal(value.provenance,'independent review');assert.equal(value.boundaryDiagnostics.fia.warnings[0],'preserve warning');
});
test('explicit per-boundary manual selection works; switching back never discards the manual position',()=>{
 const {value}=setup();
 const manual=chooseBoundarySource(value,'sector1End','manual');
 assert.equal(manual.sector1End.at,.35);assert.equal(manual.startFinish.at,.996);assert.equal(manual.boundaryEffectiveSources.sector1End,'manual');
 const back=chooseBoundarySource(manual,'sector1End','calculated');assert.equal(back.sector1End.at,.297);assert.equal(back.boundaryManualPositions.sector1End.at,.35);
 assert.equal(chooseBoundarySource(back,'sector1End','manual').sector1End.at,.35);
});
test('source choice and recoverable manual positions persist through JSON reload without a development draft',()=>{
 const {value,calculated}=setup();
 const manual=placeAnnotation(value,{kind:'sector1End'},.31);
 const stored=JSON.parse(JSON.stringify({sources:manual.boundarySources,manualPositions:manual.boundaryManualPositions,manualHistory:manual.boundaryManualHistory}));
 const refreshed=resolveBoundarySources(calculated,calculated,stored);
 assert.equal(refreshed.sector1End.at,.31);assert.equal(refreshed.boundaryEffectiveSources.sector1End,'manual');
 assert.equal(refreshed.boundaryManualHistory.sector1End[0].at,.35);
 const back=chooseBoundarySource(refreshed,'sector1End','calculated');
 const reloaded=resolveBoundarySources(calculated,calculated,JSON.parse(JSON.stringify({sources:back.boundarySources,manualPositions:back.boundaryManualPositions})));
 assert.equal(reloaded.sector1End.at,.297);assert.equal(reloaded.boundaryManualPositions.sector1End.at,.31);
});
test('missing calculations fall back to retained manual positions; new calculated data returns to the default',()=>{
 const old=legacy();const missing=resolveBoundarySources(old,null);
 assert.equal(missing.sector1End.at,.35);assert.equal(missing.boundaryEffectiveSources.sector1End,'manual-fallback-no-calculated');
 assert.equal(missing.boundarySources.sector1End,'calculated');
 const restored=resolveBoundarySources(missing,calc());assert.equal(restored.sector1End.at,.297);
 const empty=resolveBoundarySources(emptyAnnotations(circuit,geometry),null);assert.equal(empty.startFinish,null);assert.equal(empty.boundaryEffectiveSources.startFinish,'unavailable');
});
test('editor/audit source is explicit and preview agrees with the calculated default',()=>{
 const {value}=setup(),preview=calculatedBoundaryPreview(value);
 for(const key of ['startFinish','sector1End','sector2End'])assert.deepEqual(preview[key],value[key]);
 const manual=chooseBoundarySource(value,'sector2End','manual');
 const rows=boundaryDisplayAudit(manual,geometry,{annotationFile:legacy()});
 assert.equal(rows.find(r=>r.key==='sector2End').origin,'manual');assert.equal(rows.find(r=>r.key==='sector1End').origin,'calculated');
 assert.equal(calculatedBoundaryPreview(manual).sector2End.at,.709);assert.equal(manual.sector2End.at,.69);
});
test('manual edits preserve reviewed history, original calculation and export compatibility',()=>{
 const {value}=setup();const edited=editManualBoundary(value,'sector1End',{at:.32});
 assert.equal(edited.boundarySources.sector1End,'manual');assert.equal(edited.sector1End.sourceEstimate.at,.297);
 assert.equal(edited.boundaryManualHistory.sector1End[0].at,.35);assert.equal(edited.boundaryManualHistory.sector1End[0].status,'verified');
 assert.doesNotThrow(()=>validateAnnotations(JSON.parse(JSON.stringify(edited)),circuit,geometry));
});

test('editor reports the selected source and normal rendering matches calculation-only preview',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true},appType:'custom'});
 try{
  const {default:Renderer}=await server.ssrLoadModule('/src/circuits/CircuitRenderer.jsx');
  const {default:Editor}=await server.ssrLoadModule('/src/circuits/AnnotationEditor.jsx');
  const {value}=setup();const circuitProps={...circuit,name:'Fixture',flagColors:{}};
  const render=a=>renderToStaticMarkup(createElement(Renderer,{geometry,circuit:circuitProps,annotations:a}));
  assert.equal(render(value),render(calculatedBoundaryPreview(value)));
  const manual=chooseBoundarySource(value,'startFinish','manual');
  const markup=renderToStaticMarkup(createElement(Editor,{circuit:circuitProps,geometry,value:manual,onChange:()=>{},placing:null,setPlacing:()=>{},onSelect:()=>{}}));
  assert.match(markup,/Displayed source: manual/);assert.match(markup,/value="manual" selected=""/);
  const allManual=resolveBoundarySources(legacy(),null,{sources:{startFinish:'manual',sector1End:'manual',sector2End:'manual'},manualPositions:legacy()});
  assert.match(render(allManual),/data-sector="1"/);
 }finally{await server.close();}
});
