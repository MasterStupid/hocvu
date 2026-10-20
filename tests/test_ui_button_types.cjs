'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');

function assertActionButtons(html, expectedClasses) {
  const buttons = html.match(/<button\b[^>]*>/g) || [];
  assert.equal(buttons.length, expectedClasses.length);
  for (const className of expectedClasses) {
    const button = buttons.find(tag => tag.includes(`class="${className}"`));
    assert.ok(button, `missing ${className}`);
    assert.match(button, /\btype="button"/, `${className} must not submit a form`);
  }
}

test('topic and suggestion buttons explicitly avoid form submission', () => {
  const ui = loadUI();
  ui.renderSuggestionTopics([{ topic: 'Học vụ', questions: ['Điều kiện bảo lưu?'] }]);
  assertActionButtons(ui.dom.suggestions.innerHTML, ['topic-toggle', 'suggestion-chip']);
});

test('answer citations, copy and refusal follow-ups explicitly avoid form submission', () => {
  const ui = loadUI();
  const html = ui.renderAnswerCard({
    answer: 'Có căn cứ.', refused: false, card: {
      verdict_segments: [{ text: 'Có căn cứ.', cites: [1] }],
      grounding: { level: 5, label: 'mạnh', source_count: 1 },
    },
  }, [], false, 1);
  assertActionButtons(html, ['citation-chip', 'copy-btn']);
  const refusal = ui.renderAnswerCard({
    answer: 'Chưa đủ căn cứ.', refused: true, card: { suggestions: ['Điều kiện bảo lưu?'] },
  }, [], false, 2);
  assertActionButtons(refusal, ['follow-up-chip']);
});
