import { useEffect, useReducer, useRef, useState } from 'react';
import { initialRaceState, raceReducer } from './state';
import { connectRaceSocket } from './socket';

export default function useRaceFeed() {
  const [race, dispatch] = useReducer(raceReducer, undefined, initialRaceState);
  const [connection, setConnection] = useState('connecting');
  const [controls, setControls] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [controlError, setControlError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const transport = useRef(null);
  useEffect(() => {
    const client = connectRaceSocket({ url: 'ws://127.0.0.1:8765', onConnection: setConnection,
      onMessage: message => {
        if (message.type === 'controls') setControls(message.enabled === true);
        if (message.type === 'sessions') { setSessions(message.sessions ?? []); setControlError(''); }
        if (message.type === 'control-error') setControlError(message.error);
        if (message.type === 'snapshot') setControlError('');
        dispatch(message);
      } });
    transport.current = client;
    const ticker = setInterval(() => setNow(Date.now()), 250);
    return () => { clearInterval(ticker); client.close(); };
  }, []);
  return { race, connection, controls, sessions, controlError,
    clockMs: race.mode === 'TEST' ? race.clockMs : now,
    send: command => transport.current?.send(command) };
}
