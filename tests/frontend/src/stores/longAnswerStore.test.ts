import { describe, it, expect, beforeEach } from 'vitest';
import { useLongAnswerStore } from '../../../../frontend/src/renderer/stores/longAnswerStore';

describe('LongAnswerStore', () => {
  beforeEach(() => {
    useLongAnswerStore.setState({
      activeId: null,
      byId: {},
      panel: {
        visible: false,
        x: 32,
        y: 88,
        width: 480,
        height: 600,
        isDragging: false,
        isResizing: false,
      }
    });
  });

  it('should initialize correctly', () => {
    const state = useLongAnswerStore.getState();
    expect(state.activeId).toBeNull();
    expect(state.panel.visible).toBe(false);
  });

  it('should append chunks correctly and maintain idempotency issues if they arise sequentially', () => {
    const store = useLongAnswerStore.getState();
    store.appendChunk('test-id', 0, '# Hello\n');
    
    let state = useLongAnswerStore.getState();
    expect(state.byId['test-id']).toBeDefined();
    expect(state.byId['test-id'].markdown).toBe('# Hello\n');

    store.appendChunk('test-id', 1, 'World');
    state = useLongAnswerStore.getState();
    expect(state.byId['test-id'].markdown).toBe('# Hello\nWorld');
  });

  it('should update status correctly', () => {
    const store = useLongAnswerStore.getState();
    store.appendChunk('test-id', 0, '');
    
    store.updateStatus('test-id', { status: 'COMPLETED', title: 'Test Title' });
    const state = useLongAnswerStore.getState();
    
    expect(state.byId['test-id'].status).toBe('COMPLETED');
    expect(state.byId['test-id'].title).toBe('Test Title');
  });

  it('should toggle panel visibility', () => {
    const store = useLongAnswerStore.getState();
    
    store.openPanel('test-id');
    expect(useLongAnswerStore.getState().panel.visible).toBe(true);
    expect(useLongAnswerStore.getState().activeId).toBe('test-id');

    useLongAnswerStore.getState().closePanel();
    expect(useLongAnswerStore.getState().panel.visible).toBe(false);
  });
});
