const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
export const WS_URL =
  import.meta.env.VITE_WS_URL || `${wsProto}//${location.host}/ws/dashboard`;

export const API_BASE =
  import.meta.env.VITE_API_BASE || '';
