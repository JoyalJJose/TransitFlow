const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
export const WS_URL =
  import.meta.env.VITE_WS_URL || `${wsProto}//${location.host}/ws/dashboard`;
