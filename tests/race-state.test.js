import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialRaceState, raceReducer, flattenRecord, selectCircuit, validGps, tyrePresentation } from '../src/race/state.js';
import { connectRaceSocket } from '../src/race/socket.js';

function message(type, extra = {}) {
  return {version:1,type,generation:1,sequence:1,mode:'TEST',clockMs:1000,...extra};
}
test('snapshots, authoritative deltas, stale sequence rejection and session reset', () => {
  let state = raceReducer(initialRaceState(), message('snapshot',{topics:{DriverList:{1:{Tla:'VER'}}}}));
  state = raceReducer(state,message('topic',{sequence:2,topic:'TimingData',data:{1:{Position:'1'}}}));
  assert.equal(state.topics.DriverList[1].Tla,'VER');
  assert.equal(raceReducer(state,message('topic')),state);
  state = raceReducer(state,message('status',{generation:2,sessionId:'new'}));
  assert.deepEqual(state.topics,{});
  state = raceReducer(state,message('snapshot',{generation:1,sequence:1,topics:{DriverList:{4:{Tla:'NOR'}}}}));
  assert.equal(state.topics.DriverList[4].Tla,'NOR'); // server restarted; new snapshot wins
});
test('tyre/sector presentation preserves the nested authoritative source', () => {
  const nested={Stints:{0:{Compound:'SOFT',TotalLaps:4}}};
  assert.equal(flattenRecord(nested).Stints_0_Compound,'SOFT');
  assert.equal(nested.Stints[0].TotalLaps,4);
  assert.equal(tyrePresentation(nested).CurrentStint_TotalLaps,4);
  assert.equal(tyrePresentation({Stints:{0:{Compound:'SOFT'},1:{Compound:'HARD',TotalLaps:1}}}).CurrentStint_Compound,'HARD');
});
test('TEST GPS expires against archive clock, not wall time; unknown circuits stay unknown', () => {
  const gps={X:10,Y:20,_sampleTimeMs:1000};
  assert.ok(validGps(gps,1500));
  assert.ok(!validGps(gps,22000));
  assert.ok(!validGps({...gps,X:NaN},1500));
  assert.ok(!validGps(gps,-5000));
  assert.equal(selectCircuit({Meeting:{Circuit:{ShortName:'Austin'}}}),'Austin');
  assert.equal(selectCircuit({Meeting:{Circuit:{ShortName:'Monza'}}}),null);
});
test('socket reconnects with backoff, ignores bad messages and closes cleanly', () => {
  const sockets=[], timers=[], received=[], states=[], cancelled=[];
  class FakeSocket {
    constructor(){sockets.push(this);this.readyState=1;}
    close(){this.onclose?.();}
    send(value){this.sent=value;}
  }
  const client=connectRaceSocket({url:'ws://test',WebSocketClass:FakeSocket,onMessage:m=>received.push(m),onConnection:s=>states.push(s),
    schedule:(fn,delay)=>{timers.push({fn,delay});return timers.length;},cancel:id=>cancelled.push(id)});
  sockets[0].onopen();
  sockets[0].onmessage({data:'not json'});
  sockets[0].onmessage({data:'{"version":1}'});
  assert.equal(received.length,1);
  sockets[0].onclose();assert.equal(timers[0].delay,1000);
  timers[0].fn();
  sockets[1].onclose();assert.equal(timers[1].delay,2000);
  timers[1].fn();sockets[2].onopen();
  client.send({action:'play'});assert.match(sockets[2].sent,/play/);
  client.close();assert.equal(timers.length,2);
  assert.ok(cancelled.length);assert.ok(states.includes('disconnected'));
});
