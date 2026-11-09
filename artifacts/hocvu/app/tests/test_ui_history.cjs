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

test('real Python-persisted response retains its grounding, citations and exported sources', {
  skip: !process.env.HV_HISTORY_FIXTURE,
}, async () => {
  const turns = JSON.parse(fs.readFileSync(process.env.HV_HISTORY_FIXTURE, 'utf8'));
  const ui = loadUI();
  ui.restoreHistory(turns);
  const last = turns[turns.length - 1], html = botMessages(ui).at(-1).innerHTML;
  assert.match(html, new RegExp(`Căn cứ ${last.card.grounding.label} · ${last.card.grounding.source_count} nguồn`));
  assert.match(html, /data-citation="1"/);
  assert.equal(ui.speech.length, 0);
  const text = await downloadText(ui);
  for (const ref of last.references) {
    for (const value of [ref.reg_title, ref.rid, ref.aid, ref.art_heading, ref.excerpt]) {
      assert.ok(text.includes(value), `export is missing saved source field: ${value}`);
    }
    assert.ok(text.includes(`Khoản: ${ref.clause_ids.join(', ')}`));
  }
  assert.equal(ui.calls.length, 0, 'export must not query the current corpus');
});

async function downloadText(ui) {
  ui.exportConversation();
  assert.equal(ui.blobs.length, 1);
  assert.equal(ui.blobs[0].type, 'text/plain;charset=utf-8');
  assert.match(ui.downloads[0].filename, /^hocvu-ai-\d{4}-\d{2}-\d{2}\.txt$/);
  assert.equal(ui.downloads[0].href, 'blob:test-1');
  assert.deepEqual(ui.revokedURLs, ['blob:test-1']);
  assert.equal(ui.document.body.children.length, 0, 'download link is cleaned up');
  assert.match(ui.dom.liveStatus.textContent, /Đã tải tệp hội thoại/);
  return ui.blobs[0].text();
}

test('transcript keeps independent full evidence snapshots for both live and restored answers', () => {
  for (const restore of [false, true]) {
    const ui = loadUI(), response = grounded();
    response.refusal_reason = '';
    const original = JSON.parse(JSON.stringify(response));
    if (restore) ui.restoreHistory([response]);
    else ui.appendAnswer(response);
    const entry = ui.state.transcript.at(-1);
    assert.equal(entry.text, original.answer);
    for (const key of ['references', 'card', 'refused', 'refusal_reason', 'intent']) {
      assert.deepEqual(JSON.parse(JSON.stringify(entry[key])), original[key], key);
    }
    assert.equal(entry.presentation, 'answer');
    response.references[0].excerpt = 'Đã thay đổi';
    response.references[0].clause_ids.push('99');
    response.card.verdict_segments[0].cites.push(99);
    response.card.notes[0].text = 'Lưu ý khác';
    response.card.grounding.level = 0;
    assert.deepEqual(JSON.parse(JSON.stringify(entry.references)), original.references);
    assert.deepEqual(JSON.parse(JSON.stringify(entry.card)), original.card);
  }
});

test('live send exports UTF-8 text with full clauses, excerpts, assessment and citations without retrieval', async () => {
  const response = grounded('Quy chế đào tạo — Đại học Hải Phòng');
  response.question = 'Điều kiện bảo lưu “kết quả”?\nTiếng Việt: đ, ắ, ễ; 🎓';
  response.references[0].rid = 'QĐ/ĐHHP-2026';
  response.references[0].clause_ids = ['2', '3a'];
  response.references[0].excerpt = 'Khoản 2. Sinh viên được bảo lưu.\nKhoản 3a. Giữ nguyên “kết quả” <đã học> & điểm.';
  response.card.verdict_segments.push({ text: 'Cần đáp ứng quy định bổ sung.', cites: [1] });
  const ui = loadUI({ request: async () => response });
  ui.bind();
  assert.equal(ui.dom.exportConversation.events.click, ui.exportConversation);
  await ui.send(response.question);
  assert.equal(ui.calls.filter(([url]) => url !== '/api/conversations').length, 1);
  const callsBeforeExport = ui.calls.length;
  const text = await downloadText(ui);
  assert.match(text, /^HOCVU AI — LỊCH SỬ HỘI THOẠI\nXuất lúc: .+\n\nBẠN:\n/);
  for (const value of [
    response.question, 'HOCVU AI (lượt 1):',
    'Được bảo lưu khi đủ điều kiện. [1]', 'Cần đáp ứng quy định bổ sung. [1]',
    'Căn cứ mạnh · 1 nguồn · Mức 5/5', 'Lưu ý:\nÁp dụng cho sinh viên.',
    'Nguồn [1]: Quy chế đào tạo — Đại học Hải Phòng', 'Mã văn bản: QĐ/ĐHHP-2026',
    'Phiên bản: 2026', 'Điều/mục: Điều 5', 'Tiêu đề: Bảo lưu', 'Khoản: 2, 3a',
    `Trích dẫn:\n${response.references[0].excerpt}`,
  ]) assert.ok(text.includes(value), `missing: ${value}`);
  assert.doesNotMatch(text, /undefined|null|\[object Object\]|&lt;|&amp;|�/);
  const bytes = Buffer.from(await ui.blobs[0].arrayBuffer());
  assert.equal(bytes.toString('utf8'), text, 'Unicode survives the downloaded bytes');
  assert.equal(ui.calls.length, callsBeforeExport, 'export makes no additional API calls');
});

test('live and restored snapshots produce identical export bodies', async () => {
  const response = grounded();
  const live = loadUI({ request: async () => response }), restored = loadUI();
  await live.send(response.question);
  restored.restoreHistory([response]);
  const liveText = await downloadText(live), restoredText = await downloadText(restored);
  assert.equal(liveText.split('\n').slice(2).join('\n'), restoredText.split('\n').slice(2).join('\n'));
  assert.equal(restored.calls.length, 0);
});

test('multiple turns scope repeated [1] to their own original sources, not the selected sidebar', async () => {
  const first = grounded('Văn bản thứ nhất'), second = grounded('Văn bản thứ hai');
  first.question = 'Câu hỏi thứ nhất?';
  first.answer = first.card.verdict_segments[0].text = 'Kết luận thứ nhất.';
  first.references[0].excerpt = 'Đoạn trích thứ nhất.';
  second.question = 'Câu hỏi thứ hai?';
  second.answer = second.card.verdict_segments[0].text = 'Kết luận thứ hai.';
  second.references[0].aid = 'Điều 10';
  second.references[0].clause_ids = ['4'];
  second.references[0].excerpt = 'Đoạn trích thứ hai.';
  const ui = loadUI();
  ui.restoreHistory([first, second]);
  botMessages(ui)[0].querySelectorAll('[data-citation]')[0].events.click();
  assert.match(ui.dom.evidence.innerHTML, /Văn bản thứ nhất/);
  first.references[0].excerpt = 'Nội dung đã bị sửa sau khi hiển thị';
  second.references[0].clause_ids[0] = '99';
  const text = await downloadText(ui);
  const one = text.split('HOCVU AI (lượt 1):')[1].split('BẠN:')[0];
  const two = text.split('HOCVU AI (lượt 2):')[1];
  assert.match(one, /Kết luận thứ nhất\. \[1\]/);
  assert.match(one, /Nguồn \[1\]: Văn bản thứ nhất/);
  assert.match(one, /Điều\/mục: Điều 5\nTiêu đề: Bảo lưu\nKhoản: 2\nTrích dẫn:\nĐoạn trích thứ nhất\./);
  assert.doesNotMatch(one, /thứ hai|Điều 10|Khoản: 4/);
  assert.match(two, /Kết luận thứ hai\. \[1\]/);
  assert.match(two, /Nguồn \[1\]: Văn bản thứ hai/);
  assert.match(two, /Điều\/mục: Điều 10\nTiêu đề: Bảo lưu\nKhoản: 4\nTrích dẫn:\nĐoạn trích thứ hai\./);
  assert.doesNotMatch(two, /thứ nhất|Khoản: 99|Nội dung đã bị sửa/);
  assert.equal((text.match(/Nguồn \[1\]:/g) || []).length, 2);
  assert.equal(ui.calls.length, 0);
});

test('multiple references preserve snapshot ordering, duplicate document IDs and per-segment citation numbers', async () => {
  const response = grounded();
  response.references.push({
    ...response.references[0], aid: 'Điều 7', art_heading: 'Thời hạn', clause_ids: ['1', '2'],
    excerpt: 'Đoạn trích khác trong cùng văn bản.',
  });
  response.card.verdict_segments = [
    { text: 'Đối chiếu hai điều.', cites: [2, 1] },
    { text: 'Nội dung không gắn nguồn.', cites: [] },
  ];
  response.card.grounding.source_count = 2;
  const ui = loadUI();
  ui.restoreHistory([response]);
  const text = await downloadText(ui);
  assert.match(text, /Đối chiếu hai điều\. \[2\] \[1\]\nNội dung không gắn nguồn\./);
  assert.match(text, /Nguồn \[1\]:[^]*Điều\/mục: Điều 5[^]*Nguồn \[2\]:[^]*Điều\/mục: Điều 7/);
  assert.match(text, /Khoản: 1, 2\nTrích dẫn:\nĐoạn trích khác trong cùng văn bản\./);
  assert.doesNotMatch(text, /Nguồn \[3\]/);
});

test('greetings and refusals export their real status, never card-shaped evidence', async () => {
  for (const restore of [false, true]) {
    for (const kind of ['greeting', 'refusal']) {
      const response = grounded('Nguồn không được dùng');
      response.intent = kind === 'greeting' ? 'greeting' : 'academic_rules';
      response.refused = kind === 'refusal';
      response.refusal_reason = response.refused ? 'Không có quy định phù hợp.' : '';
      response.answer = response.refused ? 'Chưa tìm thấy căn cứ.' : 'Chào bạn!';
      const ui = loadUI();
      if (restore) ui.restoreHistory([response]);
      else ui.appendAnswer(response);
      const text = await downloadText(ui);
      assert.ok(text.includes(response.answer));
      assert.match(text, response.refused ? /Trạng thái: Từ chối trả lời/ : /Trạng thái: Lời chào/);
      if (response.refused) assert.match(text, /Lý do từ chối: Không có quy định phù hợp\./);
      assert.doesNotMatch(text, /Nguồn \[|Nguồn không được dùng|Căn cứ mạnh|Khoản:|Trích dẫn:|Được bảo lưu/);
    }
  }
});

test('legacy missing or partial metadata exports an explicit unknown, without reconstructing sources from IDs', async () => {
  for (const extra of [
    {},
    { references: null, card: null, refused: null },
    { refused: false, references: grounded().references, card: { grounding: {} } },
  ]) {
    const ui = loadUI();
    ui.restoreHistory([{
      question: 'Câu hỏi cũ?', answer: 'Câu trả lời cũ [1].', intent: 'academic_rules',
      rid: 'Mã cũ không xác định nguồn', article_id: 'Điều 99', ...extra,
    }]);
    const text = await downloadText(ui);
    assert.match(text, /Trạng thái: Lượt đã lưu — chi tiết căn cứ không có trong bản lưu này\./);
    assert.match(text, /Câu trả lời cũ \[1\]\./);
    assert.doesNotMatch(text, /Nguồn \[1\]:|Mã văn bản:|Điều\/mục:|Khoản:|Căn cứ yếu|Căn cứ mạnh/);
    assert.equal(ui.calls.length, 0);
  }
});

test('legacy greetings and refusals export as such, rather than unknown academic answers', async () => {
  for (const extra of [
    { intent: 'greeting' },
    { intent: 'unsafe' },
    { intent: 'academic_rules', article_id: '', rid: '' },
  ]) {
    const ui = loadUI();
    ui.restoreHistory([{ question: 'Câu hỏi cũ?', answer: 'Nội dung cũ.', ...extra }]);
    const text = await downloadText(ui);
    assert.match(text, extra.intent === 'greeting' ? /Trạng thái: Lời chào/ : /Trạng thái: Từ chối trả lời/);
    assert.doesNotMatch(text, /chi tiết căn cứ không có|Nguồn \[|Căn cứ yếu/);
  }
});

test('empty exports download nothing; New only exports the currently displayed conversation', async () => {
  const ui = loadUI({ request: async () => grounded('Chỉ nguồn mới') });
  ui.exportConversation();
  assert.match(ui.dom.liveStatus.textContent, /Chưa có hội thoại để xuất/);
  assert.equal(ui.blobs.length, 0);
  ui.restoreHistory([grounded('Nguồn không còn hiển thị')]);
  ui.startNewConversation();
  ui.exportConversation();
  assert.equal(ui.blobs.length, 0);
  await ui.send('Câu hỏi mới?');
  const text = await downloadText(ui);
  assert.match(text, /Câu hỏi mới\?/);
  assert.match(text, /HOCVU AI \(lượt 1\):/);
  assert.match(text, /Nguồn \[1\]: Chỉ nguồn mới/);
  assert.doesNotMatch(text, /Nguồn không còn hiển thị|lượt 2/);
});

test('delete button is present in settings on every screen size and bound to the real delete action', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');
  assert.match(html, /class="utility-button delete-history-button"[^>]*data-hv="delete-history"[^>]*type="button"/);
  const dialog = html.slice(html.indexOf('data-hv="settings-dialog"'), html.indexOf('</dialog>'));
  assert.match(dialog, /data-hv="delete-history"/);
  const css = fs.readFileSync(path.join(__dirname, '..', 'ui', 'styles.css'), 'utf8');
  assert.doesNotMatch(css, /\.delete-history-button\s*\{[^}]*display:\s*none/);
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
    if (url.startsWith('/api/history?')) return new Promise(resolve => { finishHistory = resolve; });
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

test('deletion notification clears only matching tabs and ignores late answer, error and audio', async () => {
  for (const fail of [false, true]) {
    const storage = new Map();
    const deleting = loadUI({ storage }), other = loadUI({ storage, realSpeech: true });
    let finish, reject;
    const waiting = loadUI({ storage, request: () => new Promise((resolve, fail) => { finish = resolve; reject = fail; }) });
    for (const ui of [deleting, other, waiting]) { ui.bind(); ui.restoreHistory([grounded()]); }
    const old = deleting.state.sessionId;
    assert.equal(other.state.sessionId, old);
    assert.equal(waiting.state.sessionId, old);
    other.state.ttsEnabled = true;
    other.speak('Câu trả lời cũ', '/api/audio/old.mp3');
    const audio = other.state.audio, lateError = audio.onerror;
    const pending = waiting.send('Điều kiện bảo lưu?');
    const unrelated = loadUI();
    unrelated.state.sessionId = 'separate';
    unrelated.bind(); unrelated.restoreHistory([grounded()]);
    await deleting.deleteHistory();
    const notice = storage.get('hv_deleted_session');
    for (const ui of [other, waiting, unrelated]) ui.storageEvent('hv_deleted_session', notice);
    assert.equal(JSON.parse(notice).sessionId, old);
    for (const ui of [other, waiting]) {
      assert.notEqual(ui.state.sessionId, old);
      assert.equal(ui.state.transcript.length, 0);
      assert.equal(ui.dom.thread.children.length, 0);
      assert.equal(ui.state.isLoading, false);
      assert.doesNotMatch(ui.dom.evidence.innerHTML, /Nội dung căn cứ gốc/);
      assert.match(ui.dom.liveStatus.textContent, /đã bị xóa/);
    }
    assert.equal(unrelated.state.sessionId, 'separate');
    assert.equal(unrelated.state.transcript.length, 2);
    assert.equal(audio.pauses, 1);
    lateError();
    assert.equal(other.synthesis.spoken.length, 0);
    if (fail) reject(new Error('Late failure'));
    else finish(grounded());
    await pending;
    assert.equal(waiting.state.transcript.length, 0);
    assert.equal(waiting.dom.thread.children.length, 0);
    assert.equal(waiting.speech.length, 0);
  }
});

test('deleted session response from an API client clears old view and never retries its question', async () => {
  const ui = loadUI({ request: async (_url, options) => {
    const sessionId = JSON.parse(options.body).session_id;
    return new Response(JSON.stringify({
      code: 'session_closed', session_id: sessionId, detail: 'Hội thoại đã bị xóa.',
    }), { status: 410 });
  } });
  const old = ui.state.sessionId;
  ui.restoreHistory([grounded()]);
  await ui.send('Điều kiện bảo lưu?');
  assert.notEqual(ui.state.sessionId, old);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.dom.thread.children.length, 0);
  assert.equal(ui.calls.length, 1, 'a deleted conversation must not be recreated by an automatic retry');
  assert.equal(ui.state.isLoading, false);
  assert.equal(ui.dom.deleteHistory.disabled, false);
});

test('returning to tab checks server for API deletion; failed checks and unrelated IDs preserve the view', async () => {
  for (const result of ['closed', 'open', 'unrelated', 'network', 401]) {
    const ui = loadUI({ request: async () => {
      if (result === 'network') throw new Error('Offline');
      if (result === 401) return new Response('{}', { status: 401 });
      return { session_id: result === 'unrelated' ? 'other' : ui.state.sessionId, closed: result !== 'open' };
    } });
    ui.bind(); ui.restoreHistory([grounded()]);
    const old = ui.state.sessionId;
    await ui.windowEvents.focus();
    assert.equal(ui.calls[0][0], `/api/history/status?session_id=${encodeURIComponent(old)}`);
    assert.equal(ui.state.sessionId === old, result !== 'closed');
    assert.equal(ui.state.transcript.length, result === 'closed' ? 0 : 2);
    assert.equal(typeof ui.windowEvents.pageshow, 'function');
    ui.document.visibilityState = 'hidden';
    ui.documentEvents.visibilitychange();
    assert.equal(ui.calls.length, 1);
  }
});

test('late status and history checks never clear or restore a different conversation', async () => {
  let finishStatus, finishHistory;
  const ui = loadUI({ request: async url => {
    if (url.startsWith('/api/history/status?')) return new Promise(resolve => { finishStatus = resolve; });
    if (url.startsWith('/api/history?')) return new Promise(resolve => { finishHistory = resolve; });
    if (url === '/api/health') return { documents: 0 };
    return [];
  } });
  const old = ui.state.sessionId;
  const pending = ui.boot();
  ui.storageEvent('hv_deleted_session', JSON.stringify({ sessionId: old }));
  const fresh = ui.state.sessionId;
  finishHistory([grounded()]);
  finishStatus({ session_id: old, closed: true });
  await pending;
  assert.equal(ui.state.sessionId, fresh);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.dom.thread.children.length, 0);
});

test('startup with a closed persisted ID does not restore a delayed pre-delete history snapshot', async () => {
  const ui = loadUI({ request: async url => {
    if (url.startsWith('/api/history/status?')) return { session_id: ui.state.sessionId, closed: true };
    if (url.startsWith('/api/history?')) return [grounded()];
    if (url === '/api/health') return { documents: 0 };
    return [];
  } });
  const old = ui.state.sessionId;
  await ui.boot();
  assert.notEqual(ui.state.sessionId, old);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.state.isRestoring, false);
  assert.equal(ui.dom.thread.children.length, 0);
});

test('New and unrelated or malformed storage changes never switch another tab', () => {
  const ui = loadUI();
  ui.bind(); ui.restoreHistory([grounded()]);
  const old = ui.state.sessionId;
  for (const [key, value] of [
    ['hv_session_id', 'new-from-other-tab'],
    ['hv_deleted_session', '{bad json'],
    ['hv_deleted_session', 'null'],
    ['hv_deleted_session', JSON.stringify({ sessionId: 1 })],
    ['hv_deleted_session', JSON.stringify({ sessionId: 'unrelated' })],
    ['hv_deleted_session', null],
  ]) ui.storageEvent(key, value);
  assert.equal(ui.state.sessionId, old);
  assert.equal(ui.state.transcript.length, 2);
  ui.startNewConversation();
  assert.equal(ui.storage.has('hv_deleted_session'), false);
});

test('failed deletion publishes no notification; simultaneous delete results cannot reset a newer view', async () => {
  const failed = loadUI({ request: async () => { throw new Error('Offline'); } });
  await failed.deleteHistory();
  assert.equal(failed.storage.has('hv_deleted_session'), false);
  let finish;
  const ui = loadUI({ request: () => new Promise(resolve => { finish = resolve; }) });
  ui.bind(); ui.restoreHistory([grounded()]);
  const old = ui.state.sessionId;
  const pending = ui.deleteHistory();
  ui.storageEvent('hv_deleted_session', JSON.stringify({ sessionId: old }));
  const fresh = ui.state.sessionId;
  finish({ status: 'deleted' });
  await pending;
  assert.equal(ui.state.sessionId, fresh);
  assert.equal(ui.state.isDeleting, false);
  assert.equal(ui.dom.deleteHistory.disabled, false);
  assert.equal(ui.state.transcript.length, 0);
});
