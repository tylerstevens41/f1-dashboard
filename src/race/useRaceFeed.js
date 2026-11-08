import {validatePrepared,sessionYear,sessionCircuitKey} from '../circuits/prepared.js';
import { useEffect, useReducer, useRef, useState } from 'react';
import { initialRaceState, raceReducer } from './state';
import { connectRaceSocket } from './socket';
import { AnimationEngine } from '../animation/engine.js';

export default function useRaceFeed() {
  const [animation] = useState(() => new AnimationEngine());
  const [race, dispatch] = useReducer(raceReducer, undefined, initialRaceState);
  const [connection, setConnection] = useState('connecting');
  const [gpsTransport,setGpsTransport]=useState({socketOpens:0,socketCloses:0,positionMessages:0,lastReceivedUtcMs:null});
  const [controls, setControls] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [liveSessions,setLiveSessions]=useState([]);
  const [circuitJobs,setCircuitJobs]=useState({});
  const [preparedBundles,setPreparedBundles]=useState({});
  const [windows, setWindows] = useState([]);
  const [controlError, setControlError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const transport = useRef(null);
  useEffect(() => {
    const client = connectRaceSocket({ url: 'ws://127.0.0.1:8765', onConnection: value=>{setConnection(value);if(value==='connected'||value==='disconnected')setGpsTransport(s=>({...s,[value==='connected'?'socketOpens':'socketCloses']:s[value==='connected'?'socketOpens':'socketCloses']+1}));},
      onMessage: message => {
        if(message.topic==='Position.z'||message.type==='snapshot'&&message.topics?.['Position.z'])setGpsTransport(s=>({...s,positionMessages:s.positionMessages+1,lastReceivedUtcMs:Date.now()}));
        if(message.type==='circuit-job'){
          setCircuitJobs(values=>({...values,[message.job.identity?.path??message.job.path??'current']:message.job}));return;
        }
        if(message.type==='circuit-assets'){
          try{const bundle=validatePrepared(message.bundle);setPreparedBundles(values=>({...values,[bundle.identity.assetKey]:bundle}));}
          catch{setControlError('Prepared circuit rejected: schema, calibration or annotation geometry mismatch.');}return;
        }
        animation.ingest(message,performance.now());
        if(message.type==='live-sessions'){setLiveSessions(message.sessions??[]);setControlError('');return;}
        if (message.type === 'windows') setWindows(message.windows ?? []);
        if (message.type === 'controls') setControls(message.enabled === true);
        if (message.type === 'sessions') { setSessions(message.sessions ?? []); setControlError(''); }
        if (message.type === 'control-error') setControlError(message.error);
        if (message.type === 'snapshot') { setControlError(''); setWindows([]); }
        dispatch(message);
      } });
    transport.current = client;
    const stopAnimation=animation.start();
    const ticker = setInterval(() => setNow(Date.now()), 250);
    return () => { clearInterval(ticker); client.close(); stopAnimation(); };
  }, [animation]);
  const session=race.topics.SessionInfo;
  const year=sessionYear(session),key=sessionCircuitKey(session),path=race.playbackInfo?.sessionPath;
  useEffect(()=>{
    if(connection==='connected'&&year&&key)transport.current?.send({action:'circuit-lookup',year,path:race.mode==='TEST'?path:undefined});
  },[connection,year,key,path,race.mode]);
  return { wallClockMs:now,gpsTransport,preparedBundles,circuitJobs,animation, race, connection, controls, sessions, liveSessions, windows, controlError,
    clockMs: race.mode === 'TEST' ? race.clockMs : now,
    send: command => transport.current?.send(command) };
}
