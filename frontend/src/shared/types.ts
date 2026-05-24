export interface WSMessage {
  type: string;
  trace_id: string;
  payload: any;
}

export interface PingPayload {
  timestamp: number;
}

export interface PongPayload {
  timestamp: number;
  source: string;
}

export interface ErrorPayload {
  code: number;
  message: string;
}
