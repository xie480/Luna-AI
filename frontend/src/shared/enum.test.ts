import { describe, it, expect } from 'vitest';
import { ErrorCode } from './enum';

describe('Constants', () => {
  it('should have correct ErrorCode values', () => {
    expect(ErrorCode.SUCCESS).toBe(0);
    expect(ErrorCode.SYSTEM_ERROR).toBe(1000);
  });
});
