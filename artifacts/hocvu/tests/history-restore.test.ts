import { describe, expect, it } from 'vitest';
import { fromRow } from '@/hooks/use-chat';
import type { HistoryRow } from '@/lib/api';

const grounding = { level: 3, label: 'trung bình', source_count: 1 };
const reference = { rid: 'R', reg_title: 'Quy định', aid: 'Điều 1', art_heading: '', clause_ids: ['1'], excerpt: 'Nội dung' };

function row(patch: Partial<HistoryRow>): HistoryRow {
  return {
    id: 1, question: 'Câu hỏi', answer: 'Trả lời', intent: 'academic_rules', refused: false,
    references: [reference], card: { grounding }, article_id: 'Điều 1', rid: 'R', ...patch,
  };
}

describe('Restoring saved turns', () => {
  it('keeps the wording mode that was saved with the answer', () => {
    for (const mode of ['on', 'off', 'fallback']) {
      const turn = fromRow(row({ card: { grounding, answer_mode: mode } }));
      expect(turn.answer?.presentation).toBe('answer');
      expect(turn.answer?.providers).toEqual({ llm: mode });
    }
  });

  it('leaves the mode unknown for older rows instead of guessing', () => {
    expect(fromRow(row({})).answer?.providers).toBeUndefined();
    expect(fromRow(row({ card: { grounding, answer_mode: 'surprise' } })).answer?.providers).toBeUndefined();
  });

  it('restores a saved refusal with its reason and suggestions', () => {
    const turn = fromRow(row({
      refused: true, references: [], article_id: '', rid: '', refusal_reason: 'Insufficient grounded context',
      card: { grounding: { level: 0, label: 'yếu', source_count: 0 }, suggestions: ['Điều kiện bảo lưu?'] },
    }));
    expect(turn.answer?.presentation).toBe('refusal');
    expect(turn.answer?.refusalReason).toBe('Insufficient grounded context');
    expect(turn.answer?.card.suggestions).toEqual(['Điều kiện bảo lưu?']);
    expect(turn.answer?.restored).toBe(true);
  });

  it('restores a saved greeting as a plain message', () => {
    const turn = fromRow(row({ intent: 'greeting', references: [], article_id: '', rid: '', card: { grounding } }));
    expect(turn.answer?.presentation).toBe('greeting');
  });
});
