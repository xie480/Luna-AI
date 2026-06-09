import { describe, expect, it } from 'vitest';
import {
  CHAT_NODE_STATUS,
  CHAT_NODE_STATUS_LABEL,
  CHAT_PLAN_PRESET,
  CHAT_WORKFLOW_EVENT_TYPE,
  CHAT_WORKFLOW_NODE_LABEL,
  CHAT_WORKFLOW_NODE_TYPE,
  CHAT_WORKFLOW_SCHEMA_VERSION,
  ErrorCode,
  WS_MSG_TYPE,
} from '../../../../frontend/src/shared/enum';

describe('shared enum constants', () => {
  it('should expose stable error code values', () => {
    expect(ErrorCode.SUCCESS).toBe(0);
    expect(ErrorCode.SYSTEM_ERROR).toBe(1000);
  });

  it('should expose phase 8.5 workflow constants without magic string drift', () => {
    expect(CHAT_WORKFLOW_SCHEMA_VERSION.CHAT_WORKFLOW_V1).toBe('chat.workflow.v1');
    expect(CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT).toBe('daily_chat.default.v1');
    expect(CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM).toBe('main_chat_llm');
    expect(CHAT_WORKFLOW_EVENT_TYPE.EVT_CHAT_PLAN_STARTED).toBe('EVT_CHAT_PLAN_STARTED');
    expect(CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION).toBe('not_entered_by_condition');
  });

  it('should keep node labels and websocket message types aligned', () => {
    expect(CHAT_WORKFLOW_NODE_LABEL[CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG]).toBe('知识库检索');
    expect(CHAT_NODE_STATUS_LABEL[CHAT_NODE_STATUS.DEGRADED]).toBe('已降级');
    expect(WS_MSG_TYPE.EVT_CHAT_PLAN_COMPLETED).toBe('EVT_CHAT_PLAN_COMPLETED');
    expect(WS_MSG_TYPE.EVT_CHAT_CONDITION_EVALUATED).toBe('EVT_CHAT_CONDITION_EVALUATED');
  });
});
