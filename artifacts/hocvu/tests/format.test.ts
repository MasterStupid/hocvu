import { describe, expect, it } from 'vitest';
import { refusalLabel } from '@/lib/format';

describe('Student-facing refusal explanations', () => {
  it.each([
    ['Insufficient grounded context', 'Nguồn hiện có'],
    ['Empty question', 'chưa nhập'],
    ['Unsafe request', 'không phù hợp'],
  ])('translates %s', (code, expected) => {
    expect(refusalLabel(code)).toContain(expected);
    expect(refusalLabel(code)).not.toContain(code);
  });

  it('does not expose unknown internal error details', () => {
    expect(refusalLabel('internal provider diagnostic')).not.toContain('diagnostic');
    expect(refusalLabel('internal provider diagnostic')).toContain('Chưa thể xác minh');
  });

  it('does not invent a reason when none was supplied', () => {
    expect(refusalLabel()).toBe('');
    expect(refusalLabel('')).toBe('');
  });
});
