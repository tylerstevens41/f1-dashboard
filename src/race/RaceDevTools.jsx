import { useState } from 'react';
import { freshnessAge, validGps } from './state';
import austin from '../circuits/tracks/austin';

function clock(value) { return Number.isFinite(value) ? `${Math.floor(value/60000)}:${String(Math.floor(value/1000)%60).padStart(2,'0')}` : '—'; }

function age(value) { return value == null ? 'no data' : `${(value / 1000).toFixed(1)}s`; }

export default function RaceDevTools({ feed, circuit }) {
  const [year, setYear] = useState(2024);
  const [path, setPath] = useState('');
  const [start, setStart] = useState(600);
  const [duration, setDuration] = useState(120);
  const { race, clockMs, controls, sessions, send } = feed;
  const gps = Object.values(race.topics['Position.z'] ?? {});
  return <details style={{ padding: 12, background: '#151922', color: 'white', fontSize: 12 }}>
    <summary>Development diagnostics · {race.mode} · {race.upstream}</summary>
    <p>WebSocket: {feed.connection} · LiveF1: {race.upstream} · Session: {race.sessionId ?? 'unknown'} · Circuit: {circuit ?? 'unsupported'}</p>
    <p><strong>{race.mode} {race.playback} · Clip {clock(race.playbackInfo?.offsetMs)} / {clock(race.playbackInfo?.durationMs)}</strong> · {race.playbackInfo?.sessionPath ?? race.sessionId ?? 'No session selected'}</p>
    <p>Clock basis: {race.clockBasis ?? 'unknown'}</p>
    <p>GPS: {gps.filter(p => validGps(p, clockMs, circuit === 'Austin' ? austin.motion.staleMs : 2500)).length} valid drivers · Last GPS: {age(freshnessAge(race, 'Position.z', clockMs))} · Timing: {age(freshnessAge(race, 'TimingData', clockMs))} · Race control: {age(freshnessAge(race, 'RaceControlMessages', clockMs))}</p>
    <p>Calibration status and measured errors are shown on the circuit panel. {circuit ? 'Use GPS calibration overlay for comparison.' : 'No mapping configured.'}</p>
    <p>{Object.entries(race.capabilities).map(([topic, status]) => `${topic}: ${status}`).join(' · ')}</p>
    {(feed.controlError || race.error) && <p role="alert">{feed.controlError || race.error}</p>}
    {controls ? <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <label>Archive year <input type="number" min="2018" max="2100" value={year} onChange={e => setYear(Number(e.target.value))} /></label>
      <button onClick={() => send({ action: 'sessions', year })}>List sessions</button>
      <select aria-label="Historical LiveF1 session" value={path} onChange={e => setPath(e.target.value)}><option value="">Select real session</option>{sessions.map(s => <option key={s.path} value={s.path}>{s.label}</option>)}</select>
      <label>Start offset (s) <input type="number" min="0" max="14400" value={start} onChange={e => setStart(Number(e.target.value))} /></label>
      <label>Clip length (s) <input type="number" min="1" max="600" value={duration} onChange={e => setDuration(Number(e.target.value))} /></label>
      <p style={{flexBasis:'100%'}}>Start offset counts seconds from the archive stream origin, not race lights-out. Clip length is the bounded window to load (maximum 600 s). For calibration try a 480 s window, then inspect on-track coverage.</p>
      <button disabled={!path} onClick={() => send({ action: 'load', path, start, duration })}>Load TEST clip</button>
      <button disabled={race.mode !== 'TEST'} onClick={() => send({ action: 'play' })}>Play / restart</button>
      <button disabled={race.mode !== 'TEST'} onClick={() => send({ action: 'pause' })}>Pause</button>
      <select aria-label="TEST speed" value={race.speed} onChange={e => send({ action: 'speed', speed: Number(e.target.value) })}>{[1,2,5,10].map(s => <option key={s} value={s}>{s}×</option>)}</select>
      <button disabled={race.mode !== 'TEST'} onClick={() => send({action:'windows'})}>Find on-track windows in loaded clip</button>
      <button onClick={() => send({ action: 'live' })}>Return to LIVE</button>
      <div style={{flexBasis:'100%'}}>{feed.windows?.length ? feed.windows.map(w=><button key={w.offsetMs} onClick={()=>setStart(w.archiveOffsetSeconds)}>Use offset {w.archiveOffsetSeconds}s · {w.onTrackDrivers} on track</button>) : 'Window search analyzes only the loaded clip. It does not scan or download a full race.'}</div>
      <span>TEST: real archive/recording only; controls affect all local viewers.</span>
    </div> : <p>Start backend with --allow-test for development controls.</p>}
  </details>;
}
