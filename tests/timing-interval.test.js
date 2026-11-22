import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {intervalToAhead} from '../src/race/timingPresentation.js';
import {initialRaceState,raceReducer} from '../src/race/state.js';

test('authoritative interval formatting never substitutes leader gap',()=>{
 assert.equal(intervalToAhead({GapToLeader:'+9.000',IntervalToPositionAhead:{Value:'+0.500'}},2),'+0.500');
 assert.equal(intervalToAhead({IntervalToPositionAhead_Value:'+1 LAP'},3),'+1 LAP');
 assert.equal(intervalToAhead({IntervalToPositionAhead:'2 LAPS'},3),'2 LAPS');
 assert.equal(intervalToAhead({IntervalToPositionAhead_Value:0},2),'0');
 for(const value of [undefined,null,'',{},false,NaN,Infinity])assert.equal(intervalToAhead({GapToLeader:'+9.000',IntervalToPositionAhead:value},2),'—');
 assert.equal(intervalToAhead({IntervalToPositionAhead:{Value:'+0.500'}},1),'—');
});

test('shared LIVE/TEST tower separates GAP and INT through authoritative timing updates and order changes',async()=>{
 const {createServer}=await import('vite');const {createElement}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server');
 const server=await createServer({server:{middlewareMode:true,hmr:false,watch:null},appType:'custom'});
 try {
  const {default:Session}=await server.ssrLoadModule('/src/LiveSession.jsx');
  const feed={connection:'connected',clockMs:0,preparedBundles:{},circuitJobs:{},animation:{configure(){}},send(){}};
  const render=()=>renderToStaticMarkup(createElement(Session,{feed}));
  const rows=html=>Array.from(html.match(/<tbody>(.*?)<\/tbody>/s)[1].matchAll(/<tr[^>]*>(.*?)<\/tr>/gs),row=>Array.from(row[1].matchAll(/<td[^>]*>(.*?)<\/td>/gs),cell=>cell[1].replace(/<[^>]+>/g,'')));
  for(const mode of ['LIVE','TEST']) {
   feed.race=raceReducer(initialRaceState(),{version:1,type:'snapshot',generation:1,sequence:1,mode,topics:{DriverList:{1:{Tla:'AAA'},2:{Tla:'BBB'},3:{Tla:'CCC'}},TimingData:{1:{Position:'1',GapToLeader:'LAP 3',IntervalToPositionAhead:{Value:'+7.777'}},2:{Position:'2',GapToLeader:'+9.000',IntervalToPositionAhead:{Value:'+0.500'}},3:{Position:'3',GapToLeader:'+10.000'}},TimingAppData:{2:{Stints:{0:{Compound:'MEDIUM',TotalLaps:12}}}}}});
   const html=render();
   assert.deepEqual(Array.from(html.matchAll(/<th\s[^>]*>(.*?)<\/th>/gs),m=>m[1]),['POS','DRIVER','GAP','TYRE','INT','BEST LAP','LAST LAP']);
   let cells=rows(html);assert.ok(cells.every(row=>row.length===7));
   assert.equal(cells[0][4],'—');assert.equal(cells[1][2],'+9.000');assert.equal(cells[1][4],'+0.500');assert.equal(cells[2][4],'—');
   assert.match(html,/live-tyre-age">12L/);assert.match(html,/\/tyres\/medium.svg/);
   feed.race=raceReducer(feed.race,{version:1,type:'topic',generation:1,sequence:2,mode,topic:'TimingData',data:{1:{Position:'2',GapToLeader:'+1 LAP',IntervalToPositionAhead:{Value:'+1 LAP'}},2:{Position:'1',GapToLeader:'LAP 4',IntervalToPositionAhead:{Value:'+0.500'}},3:{Position:'3',GapToLeader:'+20.000',IntervalToPositionAhead:{Value:'+0.222'}}}});
   cells=rows(render());assert.match(cells[0][1],/BBB/);assert.equal(cells[0][4],'—');assert.match(cells[1][1],/AAA/);assert.equal(cells[1][4],'+1 LAP');assert.equal(cells[2][4],'+0.222');
  }
 } finally {await server.close();}
});

test('compact tower sizing and tyre age typography use shared row font without widening columns',()=>{
 const css=readFileSync('src/TimingTower.css','utf8');
 const age=css.match(/\.live-tyre-age\s*\{([^}]+)\}/)[1];
 for(const rule of ['font-family: inherit','font-size: inherit','font-weight: 700','tabular-nums'])assert.ok(age.includes(rule));
 assert.match(css,/\.live-tyre-display[^}]*align-items: center[^}]*gap: 3px/);
 assert.match(css,/\.live-timing-table th, \.live-timing-table td[^}]*overflow-wrap: anywhere/);
 const component=readFileSync('src/LiveSession.jsx','utf8');
 const widths=component.match(/<colgroup>\{\[([\d,]+)\]/)[1].split(',').map(Number);
 assert.equal(widths.reduce((a,b)=>a+b),100);assert.equal(widths.length,7);
 assert.match(component,/tableLayout: "fixed"/);
 assert.match(component,/minmax\(440px, 43%\) minmax\(0, 1fr\)/);
});
