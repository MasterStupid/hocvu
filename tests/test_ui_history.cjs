'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');

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

test('delete button is present, mobile-visible, and bound to the real delete action', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');
  assert.match(html, /class="utility-button delete-history-button"[^>]*data-hv="delete-history"/);
  const css = fs.readFileSync(path.join(__dirname, '..', 'ui', 'styles.css'), 'utf8');
  assert.match(css, /\.top-actions \.delete-history-button \{ display: inline-block;/);
  const ui = loadUI();
  ui.bind();
  assert.equal(ui.dom.deleteHistory.events.click, ui.deleteHistory);
});

test('canceling permanent-delete confirmation leaves session, messages and evidence unchanged', async () => {
  const ui = loadUI({ confirm: false });
  ui.restoreHistory([grounded()]);
  const before = ui.state.sessionId, evidence = ui.dom.evidence.innerHTML;
  await ui.deleteHistory();
  assert.match(ui.confirmations[0], /vĩnh viễn/);
  assert.match(ui.confirmations[0], /hội thoại hiện tại/);
  assert.match(ui.confirmations[0], /không thể khôi phục/);
  assert.equal(ui.calls.length, 0);
  assert.equal(ui.state.sessionId, before);
  assert.equal(ui.state.transcript.length, 2);
  assert.equal(ui.dom.evidence.innerHTML, evidence);
  assert.equal(ui.dom.thread.children.length, 2);
});

test('successful deletion sends one exact session ID, clears all presentation and creates a fresh persisted ID', async () => {
  const ui = loadUI();
  ui.restoreHistory([grounded()]);
  ui.dom.input.value = 'Bản nháp';
  const old = ui.state.sessionId;
  await ui.deleteHistory();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.calls[0][0], `/api/history?session_id=${encodeURIComponent(old)}`);
  assert.equal(ui.calls[0][1].method, 'DELETE');
  assert.notEqual(ui.state.sessionId, old);
  assert.equal(ui.storage.get('hv_session_id'), ui.state.sessionId);
  assert.equal(ui.state.turn, 0);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.dom.thread.children.length, 0);
  assert.equal(ui.dom.input.value, '');
  assert.equal(ui.dom.welcome.hidden, false);
  assert.doesNotMatch(ui.dom.evidence.innerHTML, /Nội dung căn cứ gốc/);
  assert.equal(ui.state.isDeleting, false);
  assert.equal(ui.dom.deleteHistory.disabled, false);
  assert.match(ui.dom.liveStatus.textContent, /Đã xóa vĩnh viễn/);
});

test('new conversation never sends a deletion request', () => {
  const ui = loadUI();
  ui.restoreHistory([grounded()]);
  const old = ui.state.sessionId;
  ui.startNewConversation();
  assert.notEqual(ui.state.sessionId, old);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.calls.length, 0);
  assert.equal(ui.confirmations.length, 0);
});

test('failed deletion retains session and evidence, displays errors and allows retry', async () => {
  for (const failure of ['network', 401, 429, 500]) {
    const ui = loadUI({ request: async () => {
      if (failure === 'network') throw new Error('Mất kết nối');
      return new Response(JSON.stringify({ detail: 'Không thể xóa' }), { status: failure });
    } });
    ui.restoreHistory([grounded()]);
    const old = ui.state.sessionId, evidence = ui.dom.evidence.innerHTML;
    await ui.deleteHistory();
    assert.equal(ui.state.sessionId, old);
    assert.equal(ui.storage.get('hv_session_id'), old);
    assert.equal(ui.state.transcript.length, 2);
    assert.equal(ui.dom.thread.children.length, 2);
    assert.equal(ui.dom.evidence.innerHTML, evidence);
    assert.match(ui.dom.liveStatus.textContent, /Chưa thể xác nhận xóa/);
    assert.equal(ui.state.isDeleting, false);
    assert.equal(ui.dom.deleteHistory.disabled, false);
  }
});

test('pending delete locks send, session switching, duplicate delete, and voice; stops active audio', async () => {
  let finish;
  const ui = loadUI({ realSpeech: true, deferPlay: true, request: () => new Promise(resolve => { finish = resolve; }) });
  ui.restoreHistory([grounded()]);
  const old = ui.state.sessionId;
  let aborts = 0;
  ui.state.ttsEnabled = true;
  ui.speak('Câu trả lời đang đọc', '/api/audio/old.mp3');
  const audio = ui.state.audio, lateError = audio.onerror;
  ui.state.recognition = { abort() { aborts++; } };
  ui.state.recognitionRunning = true;
  ui.state.isSpeaking = true;
  const pending = ui.deleteHistory();
  assert.equal(ui.state.isDeleting, true);
  for (const control of ['deleteHistory', 'newConversation', 'send', 'mic', 'live']) {
    assert.equal(ui.dom[control].disabled, true, control);
  }
  assert.equal(audio.pauses, 1); assert.equal(aborts, 1);
  assert.equal(audio.src, '');
  assert.equal(audio.loads, 1);
  lateError();
  audio.reject(new Error('Aborted playback'));
  await Promise.resolve();
  assert.equal(ui.synthesis.spoken.length, 0);
  assert.equal(ui.state.ignoreRecognitionResults, true);
  assert.equal(ui.state.isSpeaking, false);
  await ui.deleteHistory();
  await ui.send('Điều kiện bảo lưu?');
  ui.startNewConversation();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.confirmations.length, 1);
  assert.equal(ui.state.sessionId, old);
  finish({ status: 'deleted' });
  await pending;
  assert.notEqual(ui.state.sessionId, old);
});

test('delete is unavailable while awaiting an answer or restoring history', async () => {
  const ui = loadUI();
  for (const busy of ['isLoading', 'isRestoring']) {
    ui.state[busy] = true;
    ui.updateComposer();
    assert.equal(ui.dom.deleteHistory.disabled, true);
    await ui.deleteHistory();
    assert.equal(ui.calls.length, 0);
    assert.equal(ui.confirmations.length, 0);
    ui.state[busy] = false;
  }
});

test('old answer or error arriving after New cannot populate or unlock the next conversation', async () => {
  for (const fail of [false, true]) {
    const pending = [];
    const ui = loadUI({ request: () => new Promise((resolve, reject) => pending.push({ resolve, reject })) });
    const oldSend = ui.send('Điều kiện bảo lưu?');
    assert.equal(ui.state.isLoading, true);
    ui.startNewConversation();
    const currentSend = ui.send('Điều kiện tốt nghiệp?');
    if (fail) pending[0].reject(new Error('Late error'));
    else pending[0].resolve(grounded('Nguồn cũ'));
    await oldSend;
    assert.equal(ui.state.isLoading, true, 'old request must not unlock the new one');
    assert.equal(ui.state.transcript.length, 1);
    assert.doesNotMatch(ui.dom.evidence.innerHTML, /Nguồn cũ/);
    pending[1].resolve(grounded('Nguồn mới'));
    await currentSend;
    assert.equal(ui.state.isLoading, false);
    assert.equal(ui.state.transcript.length, 2);
    assert.match(ui.dom.evidence.innerHTML, /Nguồn mới/);
  }
});

test('history arriving after New and Delete cannot restore deleted content or sources', async () => {
  let finishHistory;
  const ui = loadUI({ request: async (url, options) => {
    if (options.method === 'DELETE') return { status: 'deleted' };
    if (url.startsWith('/api/history')) return new Promise(resolve => { finishHistory = resolve; });
    if (url === '/api/health') return { documents: 0 };
    return [];
  } });
  const booting = ui.boot();
  assert.equal(ui.state.isRestoring, true);
  ui.startNewConversation();
  await ui.deleteHistory();
  const fresh = ui.state.sessionId;
  finishHistory([grounded()]);
  await booting;
  assert.equal(ui.state.sessionId, fresh);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.dom.thread.children.length, 0);
  assert.doesNotMatch(ui.dom.evidence.innerHTML, /Nội dung căn cứ gốc/);
});
