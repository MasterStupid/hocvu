'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

// Execute the real app, exposing its private functions only in this test VM.
// No alternate renderer or production test/auth bypass is shipped.
function loadUI() {
  const elements = new Map();
  const escape = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  class Element {
    constructor() {
      this.children = []; this.dataset = {}; this.events = {}; this.cache = new Map();
      this.classList = { add() {}, remove() {}, toggle() {} }; this.style = {};
    }
    set textContent(value) { this.text = value; this.html = null; }
    get textContent() { return this.text || ''; }
    set innerHTML(value) { this.html = value; this.cache.clear(); }
    get innerHTML() { return this.html ?? escape(this.text || ''); }
    appendChild(child) { this.children.push(child); }
    addEventListener(name, callback) { this.events[name] = callback; }
    scrollIntoView() { this.scrolled = true; }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    querySelectorAll(selector) {
      if (this.cache.has(selector)) return this.cache.get(selector);
      let items = [];
      const attribute = selector === '[data-citation]' ? 'citation' : selector === '[data-source-index]' ? 'source-index' : null;
      if (attribute) {
        items = [...this.innerHTML.matchAll(new RegExp(`data-${attribute}="([^"]+)"`, 'g'))].map(match => {
          const item = new Element();
          item.dataset[attribute === 'citation' ? 'citation' : 'sourceIndex'] = match[1];
          return item;
        });
      } else if (selector === '.copy-btn' && this.innerHTML.includes('class="copy-btn"')) {
        items = [new Element()];
      }
      this.cache.set(selector, items);
      return items;
    }
  }
  const document = {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new Element());
      return elements.get(selector);
    },
    querySelectorAll() { return []; },
    createElement() { return new Element(); },
    getElementById() { return new Element(); },
    addEventListener() {},
  };
  const sandbox = {
    document, localStorage: { getItem() { return null; }, setItem() {} },
    crypto: { randomUUID() { return 'test-session'; } },
    navigator: {}, window: {}, console, setTimeout() { return 1; },
  };
  const filename = path.join(__dirname, '..', 'ui', 'main.js');
  const source = fs.readFileSync(filename, 'utf8');
  assert.match(source, /\}\)\(\);\s*$/);
  const instrumented = source.replace(/\}\)\(\);\s*$/, `
    globalThis.testUI = {
      renderAnswerCard, appendAnswer, restoreHistory, state, dom,
      setSpeechHook(callback) { speak = callback; }
    };
  })();`);
  vm.runInNewContext(instrumented, sandbox, { filename });
  const ui = sandbox.testUI;
  ui.speech = [];
  ui.setSpeechHook((...args) => ui.speech.push(args));
  return ui;
}

function grounded(title = 'Quy định bảo lưu') {
  return {
    question: 'Điều kiện bảo lưu?', answer: 'Được bảo lưu khi đủ điều kiện.',
    intent: 'academic_rules', refused: false, confidence: 0.95,
    references: [{
      rid: title, reg_title: title, version: '2026', aid: 'Điều 5', art_heading: 'Bảo lưu',
      clause_ids: ['2'], excerpt: 'Nội dung căn cứ gốc.',
    }],
    card: {
      verdict_segments: [{ text: 'Được bảo lưu khi đủ điều kiện.', cites: [1] }],
      grounding: { level: 5, label: 'mạnh', source_count: 1 },
      notes: [{ icon: 'scope', text: 'Áp dụng cho sinh viên.' }],
    },
  };
}
const botMessages = ui => ui.dom.thread.children.filter(item => item.className.startsWith('message bot'));

test('restored grounded answers retain strength, citations, notes and complete sources', () => {
  const ui = loadUI();
  ui.restoreHistory([grounded()]);
  const html = botMessages(ui)[0].innerHTML;
  assert.match(html, /Căn cứ mạnh · 1 nguồn/);
  assert.match(html, /data-citation="1"/);
  assert.match(html, /Áp dụng cho sinh viên/);
  assert.match(ui.dom.evidence.innerHTML, /Nội dung căn cứ gốc/);
  assert.doesNotMatch(html, /Căn cứ yếu · 0 nguồn/);
  assert.equal(ui.speech.length, 0, 'restoring never triggers speech');
});

test('live and restored grounded answers have the same assessment', () => {
  const live = loadUI(), restored = loadUI();
  live.appendAnswer(grounded());
  restored.restoreHistory([grounded()]);
  const meter = html => html.match(/<span class="grounding-meter[^]*?<\/span>/)[0];
  assert.equal(meter(botMessages(live)[0].innerHTML), meter(botMessages(restored)[0].innerHTML));
});

test('explicit refusal restores the refusal card and suggestions, not a conclusion', () => {
  const ui = loadUI();
  ui.restoreHistory([{
    question: 'Câu ngoài phạm vi', answer: 'Chưa đủ căn cứ.', intent: 'academic_rules', refused: true,
    references: [], card: { suggestions: ['Điều kiện bảo lưu?'] },
  }]);
  const message = botMessages(ui)[0];
  assert.match(message.className, /refused/);
  assert.match(message.innerHTML, /refusal-card/);
  assert.match(message.innerHTML, /follow-up-chip/);
  assert.doesNotMatch(message.innerHTML, /Phiếu kết quả tra cứu|Căn cứ yếu|<h3>Kết luận/);
});

test('live and legacy restored greetings are plain chat, never academic cards', () => {
  for (const restore of [false, true]) {
    const ui = loadUI();
    const response = { question: 'Xin chào', answer: 'Chào bạn!', intent: 'greeting' };
    if (restore) ui.restoreHistory([response]);
    else ui.appendAnswer({ ...response, refused: false, references: [], card: grounded().card });
    const html = botMessages(ui)[0].innerHTML;
    assert.match(html, /Chào bạn!/);
    assert.match(html, /greeting-message/);
    assert.doesNotMatch(html, /card-bubble|answer-card|grounding-meter|Phiếu kết quả|Nguồn đã đối chiếu|Kết luận/);
  }
});

test('legacy unknown and incomplete metadata are displayed explicitly without invented evidence', () => {
  for (const extra of [{}, { refused: false, references: [], card: { grounding: {} } }]) {
    const ui = loadUI();
    ui.restoreHistory([{ question: 'Câu hỏi cũ', answer: 'Câu trả lời cũ.', intent: 'academic_rules', ...extra }]);
    const html = botMessages(ui)[0].innerHTML;
    assert.match(html, /Câu trả lời cũ/);
    assert.match(html, /Chi tiết căn cứ không có/);
    assert.doesNotMatch(html, /answer-card|grounding-meter|Căn cứ yếu|<h3>Kết luận/);
  }
});

test('legacy unsafe and source-less academic refusals retain refusal presentation', () => {
  for (const legacy of [
    { intent: 'unsafe' },
    { intent: 'academic_rules', article_id: '', rid: '', refused: null },
  ]) {
    const ui = loadUI();
    ui.restoreHistory([{ question: 'Câu hỏi cũ', answer: 'Tôi chưa có căn cứ trả lời.', ...legacy }]);
    const html = botMessages(ui)[0].innerHTML;
    assert.match(html, /refusal-card/);
    assert.doesNotMatch(html, /<h3>Kết luận|Căn cứ yếu/);
  }
});

test('clicking an older citation selects that turn sources, not the latest turn sources', () => {
  const ui = loadUI();
  ui.restoreHistory([grounded('Nguồn thứ nhất'), grounded('Nguồn thứ hai')]);
  assert.match(ui.dom.evidence.innerHTML, /Nguồn thứ hai/);
  botMessages(ui)[0].querySelectorAll('[data-citation]')[0].events.click();
  assert.match(ui.dom.evidence.innerHTML, /Nguồn thứ nhất/);
  assert.doesNotMatch(ui.dom.evidence.innerHTML, /Nguồn thứ hai/);
});

test('saved and greeting text remain escaped instead of becoming executable HTML', () => {
  const ui = loadUI();
  ui.restoreHistory([{ question: '<script>bad()</script>', answer: '<img src=x onerror=bad()>', intent: 'greeting' }]);
  const html = botMessages(ui)[0].innerHTML;
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img/);
  const response = grounded('<script>bad()</script>');
  ui.restoreHistory([response]);
  assert.doesNotMatch(ui.dom.evidence.innerHTML, /<script>/);
});

test('real Python-persisted response retains its grounding and citation markers in the UI', {
  skip: !process.env.HV_HISTORY_FIXTURE,
}, () => {
  const turns = JSON.parse(fs.readFileSync(process.env.HV_HISTORY_FIXTURE, 'utf8'));
  const ui = loadUI();
  ui.restoreHistory(turns);
  const last = turns[turns.length - 1], html = botMessages(ui).at(-1).innerHTML;
  assert.match(html, new RegExp(`Căn cứ ${last.card.grounding.label} · ${last.card.grounding.source_count} nguồn`));
  assert.match(html, /data-citation="1"/);
  assert.equal(ui.speech.length, 0);
});
