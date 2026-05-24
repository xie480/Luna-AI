export interface WSMessage {
  type: string;
  trace_id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

export interface ChatRequestPayload {
  message: string;
}

export interface ChatStreamPayload {
  chunk: string;
  is_finished: boolean;
  node_id: string;
  error?: string;
}
