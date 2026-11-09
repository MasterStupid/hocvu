'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');

const items = ui => ui.dom.conversationList.children.filter(child => child.dataset.sessionId);
const label = item => item.children.map(child => child.textContent).join(' ');
const activeId = ui => items(ui).find(item => item['aria-current'] === 'page')?.dataset.sessionId;

const saved = id => ({
  session_id: id, title: `Câu hỏi ${id}`, turn_count: 1, updated_at: '2026-10-20T02:00:00Z',
});
const history = id => [{
  question: `Câu hỏi ${id}`, answer: `Trả lời ${id}`, intent: 'academic_rules',
  refused: false, references: [{ reg_title: `Nguồn ${id}`, excerpt: `Căn cứ gốc ${id}` }],
  card: {
    grounding: { level: 5, label: 'mạnh', source_count: 1 },
    verdict_segments: [{ text: `Trả lời ${id}`, cites: [1] }],
  },
}];
function routes(url) {
  if (url === '/api/conversations') return [saved('first'), saved('second')];
  if (url.startsWith('/api/history/status?')) return { closed: false };
  if (url.startsWith('/api/history?')) return history(new URL(url, 'http://test').searchParams.get('session_id'));
  if (url === '/api/health') return { documents: 0 };
  return [];
}

test('history list loads only API-scoped rows and renders hostile titles as plain text', async () => {
  const ui = loadUI({ request: async () => [saved('<script>bad</script>')] });
  await ui.refreshConversations();
  const options = items(ui);
  assert.equal(options.length, 2);
  assert.equal(options[1].dataset.sessionId, '<script>bad</script>');
  assert.match(label(options[1]), /<script>bad<\/script>/);
  for (const child of options[1].children) assert.doesNotMatch(child.innerHTML, /<script>/);
  assert.match(label(options[1]), /1 lượt/);
  assert.match(ui.dom.conversationStatus.textContent, /1 hội thoại đã lưu/);
  const key = ui.storage.get('hv_conversation_owner');
  assert.match(key, /^[a-f0-9]{64}$/);
  assert.equal(ui.calls[0][1].headers['X-HocVu-Owner'], key);
});

test('switching restores selected messages, original evidence, no speech and persists across reload', async () => {
  const storage = new Map();
  const ui = loadUI({ storage, request: async url => routes(url) });
  await ui.refreshConversations();
  await ui.selectConversation('first');
  assert.equal(ui.state.sessionId, 'first');
  assert.equal(storage.get('hv_session_id'), 'first');
  assert.match(ui.dom.evidence.innerHTML, /Căn cứ gốc first/);
  await ui.selectConversation('second');
  assert.equal(ui.state.transcript.length, 2);
  assert.match(ui.state.transcript[1].text, /second/);
  assert.doesNotMatch(ui.dom.evidence.innerHTML, /first/);
  assert.match(ui.dom.evidence.innerHTML, /Căn cứ gốc second/);
  assert.equal(ui.speech.length, 0);
  const reloaded = loadUI({ storage, request: async url => routes(url) });
  await reloaded.boot();
  assert.equal(reloaded.state.sessionId, 'second');
  assert.equal(activeId(reloaded), 'second');
  assert.match(reloaded.dom.evidence.innerHTML, /Căn cứ gốc second/);
  assert.equal(reloaded.calls[0][1].headers['X-HocVu-Owner'], ui.calls[0][1].headers['X-HocVu-Owner']);
});

test('history items and refresh controls invoke actual selection and refresh behavior', async () => {
  const ui = loadUI({ request: async url => routes(url) });
  ui.bind();
  await ui.refreshConversations();
  items(ui).find(item => item.dataset.sessionId === 'first').events.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.state.sessionId, 'first');
  assert.equal(ui.state.transcript.length, 2);
  ui.dom.conversationRefresh.events.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(ui.calls.some(([url]) => url === '/api/conversations'));
});

test('New preserves saved options; deleting selected removes only that option and creates fresh ID', async () => {
  const ui = loadUI({ request: async (url, options) => options.method === 'DELETE' ? { status: 'deleted' } : routes(url) });
  await ui.refreshConversations();
  await ui.selectConversation('first');
  ui.startNewConversation();
  assert.equal(ui.state.conversations.length, 2);
  await ui.selectConversation('second');
  await ui.deleteHistory();
  assert.notEqual(ui.state.sessionId, 'second');
  assert.equal(ui.storage.get('hv_session_id'), ui.state.sessionId);
  assert.equal(ui.state.transcript.length, 0);
  assert.equal(ui.state.conversations.length, 1);
  assert.equal(ui.state.conversations[0].session_id, 'first');
  assert.match(ui.confirmations[0], /vĩnh viễn/);
  const deletes = ui.calls.filter(([, options]) => options.method === 'DELETE');
  assert.equal(deletes.length, 1);
  assert.equal(deletes[0][0], '/api/history?session_id=second');
});

test('cancel or failed selected deletion keeps picker selection, messages and evidence', async () => {
  for (const cancel of [true, false]) {
    const ui = loadUI({ confirm: !cancel, request: async (url, options) => {
      if (options.method === 'DELETE') throw new Error('Offline');
      return routes(url);
    } });
    await ui.refreshConversations(); await ui.selectConversation('first');
    const evidence = ui.dom.evidence.innerHTML;
    await ui.deleteHistory();
    assert.equal(ui.state.sessionId, 'first');
    assert.equal(activeId(ui), 'first');
    assert.equal(ui.state.conversations.length, 2);
    assert.equal(ui.state.transcript.length, 2);
    assert.equal(ui.dom.evidence.innerHTML, evidence);
  }
});

test('rapid switching ignores late history/error and keeps composer locked for current restoration', async () => {
  for (const fail of [false, true]) {
    const pending = {};
    const ui = loadUI({ request: (url) => {
      if (url.startsWith('/api/history/status?')) return { closed: false };
      const id = new URL(url, 'http://test').searchParams.get('session_id');
      return new Promise((resolve, reject) => { pending[id] = { resolve, reject }; });
    } });
    const first = ui.selectConversation('first');
    const second = ui.selectConversation('second');
    if (fail) pending.first.reject(new Error('Late error'));
    else pending.first.resolve(history('first'));
    await first;
    assert.equal(ui.state.isRestoring, true);
    assert.equal(ui.dom.send.disabled, true);
    assert.equal(ui.state.transcript.length, 0);
    pending.second.resolve(history('second'));
    await second;
    assert.equal(ui.state.isRestoring, false);
    assert.equal(ui.state.transcript.length, 2);
    assert.match(ui.dom.evidence.innerHTML, /second/);
    assert.doesNotMatch(ui.dom.evidence.innerHTML, /first/);
  }
});

test('list failures keep previous selection and allow refresh, without erasing saved options', async () => {
  let fail = false;
  const ui = loadUI({ request: async url => {
    if (fail) throw new Error('Mất kết nối');
    return routes(url);
  } });
  await ui.refreshConversations(); await ui.selectConversation('first');
  fail = true;
  await ui.refreshConversations();
  assert.equal(ui.state.conversations.length, 2);
  assert.equal(activeId(ui), 'first');
  assert.match(ui.dom.conversationStatus.textContent, /Không thể tải danh sách/);
});

test('failed restoration blocks hidden-context send; refresh retries; New can still escape', async () => {
  let fail = true;
  const ui = loadUI({ request: async url => {
    if (fail && url.startsWith('/api/history?')) throw new Error('Offline');
    return routes(url);
  } });
  ui.bind();
  await ui.selectConversation('first');
  assert.equal(ui.state.isRestoring, true);
  assert.equal(ui.dom.deleteHistory.disabled, true);
  const before = ui.calls.length;
  await ui.send('Không gửi khi chưa tải xong');
  assert.equal(ui.calls.length, before);
  fail = false;
  ui.dom.conversationRefresh.events.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.state.isRestoring, false);
  assert.equal(ui.state.transcript.length, 2);
  ui.startNewConversation();
  assert.equal(ui.state.isRestoring, false);
  assert.equal(ui.state.transcript.length, 0);
});

test('inaccessible legacy/foreign saved ID opens fresh conversation without claiming or deleting it', async () => {
  const storage = new Map([['hv_session_id', 'legacy']]);
  const ui = loadUI({ storage, request: async url => {
    if (url.startsWith('/api/history')) return new Response(JSON.stringify({
      code: 'session_unavailable', detail: 'Ngoài phạm vi',
    }), { status: 404 });
    return routes(url);
  } });
  await ui.boot();
  assert.notEqual(ui.state.sessionId, 'legacy');
  assert.equal(ui.state.isRestoring, false);
  assert.equal(ui.state.transcript.length, 0);
  assert.match(ui.dom.liveStatus.textContent, /bản lưu cũ không bị xóa/);
  assert.ok(ui.calls.every(([, options]) => !['DELETE', 'POST'].includes(options.method)));
});

test('a pre-delete list snapshot cannot reinsert deleted conversation and cross-tab removal updates options', async () => {
  let finish;
  const ui = loadUI({ request: async (url, options) => {
    if (url === '/api/conversations') return new Promise(resolve => { finish = resolve; });
    return options.method === 'DELETE' ? { status: 'deleted' } : routes(url);
  } });
  ui.state.conversations = [saved('first'), saved('second')];
  await ui.selectConversation('first');
  const refresh = ui.refreshConversations();
  await ui.deleteHistory();
  finish([saved('first'), saved('second')]);
  await refresh;
  assert.deepEqual(Array.from(ui.state.conversations, row => row.session_id), ['second']);
  ui.bind();
  const current = ui.state.sessionId;
  ui.storageEvent('hv_deleted_session', JSON.stringify({ sessionId: 'second' }));
  assert.equal(ui.state.sessionId, current);
  assert.equal(ui.state.conversations.length, 0);
});
