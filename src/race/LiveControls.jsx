import {useState} from 'react';
import {liveTrackingStatus} from './liveStatus';
export default function LiveControls({feed}){
 const [path,setPath]=useState('');
 const {race,connection,send,liveSessions=[]}=feed;
 const info=race.topics.SessionInfo;
 return <div style={{padding:'8px 16px',background:'#151922',color:'white',display:'flex',gap:10,flexWrap:'wrap',alignItems:'center'}}>
  <strong role="status">{liveTrackingStatus(race,connection,feed.clockMs)}</strong>
  <button disabled={connection!=='connected'} onClick={()=>send({action:'live-sessions'})}>Discover race sessions</button>
  <select aria-label="LIVE session" value={path} onChange={e=>setPath(e.target.value)}><option value="">Current LIVE feed (automatic)</option>{liveSessions.map(s=><option key={s.path} value={s.path}>{s.label}</option>)}</select>
  <button disabled={connection!=='connected'} onClick={()=>send({action:'live',...(path?{path}: {})})}>Start LIVE</button>
  <button disabled={connection!=='connected'||race.mode!=='LIVE'} onClick={()=>send({action:'live-stop'})}>Stop LIVE</button>
  <span>{race.mode==='LIVE' ? `${info?.Meeting?.Name??'Session not received'} · ${info?.Name??''}`:'Use existing TEST controls below for historical playback.'}</span>
  {(feed.controlError||race.error)&&<span role="alert">{feed.controlError||race.error}</span>}
  <small>LIVE uses the current upstream feed; session choices validate its identity, never load an archive.</small>
 </div>;
}
