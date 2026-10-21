'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');

const card = (text, refs = []) => ({
  answer: text, refused: false, references: refs,
  card: { verdict_segments: [{ text, cites: [1] }], grounding: { level: 4, label: 'mạnh', source_count: refs.length } },
});
const ref = { rid: 'QĐ-1', reg_title: 'Quy chế <đào tạo>', version: '2026', aid: 'Điều 5', art_heading: 'Bảo lưu', clause_ids: ['2'], excerpt: 'Trích <b>đoạn</b>.' };

test('answer lists and pipe tables render as escaped structured HTML', () => {
  const ui = loadUI();
  const text = 'Điều kiện:\n- Có **đơn** <xin>\n- Đủ học phí\n\n| Mức | Điểm |\n|---|---|\n| Giỏi | 8.0 <b> |';
  const html = ui.renderAnswerCard(card(text), [], false, 1);
  assert.match(html, /<ul><li>Có <strong>đơn<\/strong> &lt;xin&gt;<\/li><li>Đủ học phí<\/li><\/ul>/);
  assert.match(html, /<table><thead><tr><th>Mức<\/th><th>Điểm<\/th><\/tr><\/thead><tbody><tr><td>Giỏi<\/td><td>8\.0 &lt;b&gt;<\/td><\/tr>/);
  assert.doesNotMatch(html, /<xin>|<b> /);
  assert.match(html, /data-citation="1"/);
});

test('ordered lists keep their starting number and plain paragraphs keep line breaks', () => {
  const ui = loadUI();
  const html = ui.renderAnswerCard(card('Dòng một\nDòng hai\n\n3. Bước ba\n4. Bước bốn'), [], false, 1);
  assert.match(html, /<p>Dòng một<br>Dòng hai<\/p>/);
  assert.match(html, /<ol start="3"><li>Bước ba<\/li><li>Bước bốn<\/li><\/ol>/);
});

test('each answer card carries its own collapsible, escaped source list', () => {
  const ui = loadUI();
  const html = ui.renderAnswerCard(card('Có căn cứ.', [ref]), [ref], false, 7);
  assert.match(html, /<details class="card-sources"/);
  assert.match(html, /id="answer-7-src-1"/);
  assert.match(html, /Quy chế &lt;đào tạo&gt; · Bản 2026/);
  assert.match(html, /Trích &lt;b&gt;đoạn&lt;\/b&gt;\./);
  assert.doesNotMatch(html, /<b>đoạn/);
});
