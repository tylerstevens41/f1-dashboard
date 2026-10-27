import { useEffect, useReducer, useRef, useState } from 'react';
import { initialRaceState, raceReducer } from './state';
import { connectRaceSocket } from './socket';
import { AnimationEngine } from '../animation/engine.js';

export default function useRaceFeed() {
  const [animation] = useState(() => new AnimationEngine());
  const [race, dispatch] = useReducer(raceReducer, undefined, initialRaceState);
  const [connection, setConnection] = useState('connecting');
  const [controls, setControls] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [windows, setWindows] = useState([]);
  const [controlError, setControlError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const transport = useRef(null);
  useEffect(() => {
    const client = connectRaceSocket({ url: 'ws://127.0.0.1:8765', onConnection: setConnection,
      onMessage: message => {
        animation.ingest(message,performance.now());
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
  return { animation, race, connection, controls, sessions, windows, controlError,
    clockMs: race.mode === 'TEST' ? race.clockMs : now,
    send: command => transport.current?.send(command) };
}
