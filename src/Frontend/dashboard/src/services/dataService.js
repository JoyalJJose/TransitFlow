import { WS_URL } from '../config/api';

/**
 * Subscribe to real-time dashboard data via a persistent WebSocket.
 *
 * The FastAPI server pushes a full JSON payload whenever the underlying
 * database changes.  On connect the server sends an immediate snapshot
 * so the UI never starts empty.
 *
 * @param {(data: object) => void} onMessage  Called with each dashboard payload.
 * @param {(err: Event|Error) => void} onError Called on connection / parse errors.
 * @returns {() => void} unsubscribe -- call to stop receiving data and clean up.
 */
export function subscribeToDashboard(onMessage, onError) {
  let socket;
  let reconnectTimer;
  let disposed = false;
  const RECONNECT_DELAY_MS = 3000;

  function connect() {
    if (disposed) return;

    socket = new WebSocket(WS_URL);

    socket.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (err) {
        onError(err);
      }
    });

    socket.addEventListener('error', (event) => {
      onError(event);
    });

    socket.addEventListener('close', () => {
      if (!disposed) {
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    });
  }

  connect();

  return () => {
    disposed = true;
    clearTimeout(reconnectTimer);
    if (socket) {
      socket.close();
    }
  };
}
