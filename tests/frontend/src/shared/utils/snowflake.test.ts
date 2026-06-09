import { describe, expect, it } from 'vitest';
import { Snowflake, generateId, initGlobalNode } from '../../../../../frontend/src/shared/utils/snowflake';

describe('Snowflake', () => {
  it('should generate unique IDs', () => {
    const node = new Snowflake(1);
    const id1 = node.generate();
    const id2 = node.generate();

    expect(id1).not.toBe(id2);
  });

  it('should generate monotonically increasing IDs', () => {
    const node = new Snowflake(1);
    const id1 = BigInt(node.generate());
    const id2 = BigInt(node.generate());

    expect(id1 < id2).toBe(true);
  });

  it('should throw error for invalid node ID', () => {
    expect(() => new Snowflake(-1)).toThrow();
    expect(() => new Snowflake(1024)).toThrow();
  });

  it('should generate IDs using global node', () => {
    initGlobalNode(2);
    const id1 = generateId();
    const id2 = generateId();

    expect(id1).not.toBe(id2);
    expect(typeof id1).toBe('string');
    expect(id1.length).toBeGreaterThan(0);
  });
});
