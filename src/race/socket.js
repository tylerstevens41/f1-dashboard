// Injectable transport makes reconnect/snapshot behavior testable without a race.
export function connectRaceSocket({ url, WebSocketClass = WebSocket, onMessage, onConnection,
  schedule = setTimeout, cancel = clearTimeout }) {
  let active = true;
  let socket;
  let timer;
  let attempt = 0;
  function connect() {
    if (!active) return;
    onConnection('connecting');
    socket = new WebSocketClass(url);
    const current = socket;
    current.onopen = () => { if (active && current === socket) { attempt = 0; onConnection('connected'); } };
    current.onmessage = event => {
      if (!active || current !== socket) return;
      try { onMessage(JSON.parse(event.data)); } catch { /* Invalid JSON never changes race state. */ }
    };
    current.onerror = () => { if (active && current === socket) onConnection('error'); };
    current.onclose = () => {
      if (!active || current !== socket) return;
      onConnection('disconnected');
      timer = schedule(connect, Math.min(1000 * 2 ** attempt++, 15000));
    };
  }
  connect();
  return {
    send: command => { if (socket?.readyState === 1) socket.send(JSON.stringify(command)); },
    close: () => { active = false; cancel(timer); socket?.close(); },
  };
}
