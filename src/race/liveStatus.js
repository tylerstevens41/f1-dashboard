import {validGps} from './state.js';
export function liveTrackingStatus(race,connection,now){
 if(race.mode!=='LIVE')return 'TEST — historical playback';
 if(connection!=='connected')return 'LIVE disconnected — WebSocket '+connection;
 const upstream=race.upstream;
 if(['authentication-error','connection-error','subscription-error'].includes(upstream))return 'LIVE '+upstream;
 if(upstream==='connecting')return 'Connecting to LiveF1';
 if(upstream==='waiting-session')return 'Waiting for selected LIVE session';
 if(['idle','disconnected','error'].includes(upstream))return 'LIVE disconnected';
 const status=race.topics.SessionStatus?.Status;
 if(['Finished','Finalised','Ended','Ends'].includes(status))return 'Session ended';
 if(!race.topics.SessionInfo)return 'Waiting for LIVE session metadata';
 const positions=Object.values(race.topics['Position.z']??{});
 if(positions.some(p=>validGps(p,now,5000)&&(p.X!==0||p.Y!==0)))return 'Receiving LIVE GPS telemetry';
 if(positions.length)return 'Telemetry stale — waiting for fresh GPS';
 return race.topics.SessionInfo?'Connected, awaiting GPS telemetry':'Waiting for LIVE session metadata';
}
