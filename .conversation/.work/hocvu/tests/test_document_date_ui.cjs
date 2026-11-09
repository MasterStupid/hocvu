const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const { createDateEditor } = require('../ui/document-date-editor.js');
const api = require('../ui/api-errors.js');

class Element {
  constructor() {
    this.listeners = {};
    this.value = '';
    this.disabled = false;
    this.valid = true;
    this.open = false;
    this.dataset = {};
  }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  fire(name, event = {}) { return this.listeners[name]?.({ preventDefault() {}, ...event }); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() { this.focused = true; }
  checkValidity() { return this.valid; }
  reportValidity() { this.reported = true; }
  querySelectorAll(selector) { return this.matches?.[selector] || []; }
}

function setup(request = async () => ({ id: 'upload', document_date: '2026-10-01' }), onSaved = async () => {}) {
  const nodes = Object.fromEntries(
    ['dialog', 'form', 'input', 'name', 'status', 'cancel', 'save'].map(key => [key, new Element()]),
  );
  const calls = [];
  const saved = [];
  const editor = createDateEditor({
    ...nodes,
    request: async (...args) => { calls.push(args); return request(...args); },
    onSaved: async item => { saved.push(item); return onSaved(item); },
  });
  editor.open({ id: 'upload', title: 'Quy định học vụ', document_date: '2026-12-31' });
  return { ...nodes, editor, calls, saved };
}

test('open prefills the old date and uses safe text for document titles', () => {
  const view = setup();
  view.editor.open({ id: 'upload', title: '<script>not HTML</script>', document_date: '2026-10-01' });
  assert.equal(view.dialog.open, true);
  assert.equal(view.input.value, '2026-10-01');
  assert.equal(view.name.textContent, '<script>not HTML</script>');
  assert.equal(view.input.focused, true);
  assert.match(view.status.textContent, /tệp gốc được giữ nguyên/);
});

test('valid date sends PATCH only, refreshes the list and closes on success', async () => {
  const view = setup();
  view.input.value = '2026-10-01';
  await view.form.fire('submit');
  assert.equal(view.calls.length, 1);
  assert.equal(view.calls[0][0], '/api/documents/upload/date');
  assert.equal(view.calls[0][1].method, 'PATCH');
  assert.deepEqual(JSON.parse(view.calls[0][1].body), { document_date: '2026-10-01' });
  assert.equal(view.saved.length, 1);
  assert.equal(view.dialog.open, false);
  assert.equal(view.save.disabled, false);
});

test('invalid or empty dates stay editable without sending requests', async () => {
  for (const [value, valid] of [['', true], ['2026-02-31', false]]) {
    const view = setup();
    view.input.value = value;
    view.input.valid = valid;
    await view.form.fire('submit');
    assert.equal(view.calls.length, 0);
    assert.equal(view.dialog.open, true);
    assert.equal(view.input.reported, true);
    assert.match(view.status.textContent, /ngày áp dụng hợp lệ/);
  }
});

for (const [code, detail] of [
  [400, 'Ngày áp dụng phải là ngày hợp lệ theo định dạng YYYY-MM-DD.'],
  [401, 'Sign in with username hocvu and your access password.'],
  [403, 'Cross-site changes are not allowed.'],
  [404, 'Không tìm thấy tài liệu.'],
  [503, 'Chưa thể cập nhật ngày và chỉ mục. Hãy thử lại; ngày áp dụng cũ được giữ nguyên.'],
]) {
  test(`HTTP ${code} is shown in the editor and preserves the entered date for retry`, async () => {
    const view = setup(async () => api.readResponse(
      { ok: false, json: async () => ({ detail }) }, 'fallback',
    ));
    view.input.value = '2026-10-01';
    await view.form.fire('submit');
    assert.equal(view.status.textContent, detail);
    assert.match(view.status.className, /error/);
    assert.equal(view.dialog.open, true);
    assert.equal(view.input.value, '2026-10-01');
    assert.equal(view.input.disabled, false);
    assert.equal(view.saved.length, 0);
  });
}

test('pending request disables controls, duplicate saves and Escape/cancel', async () => {
  let complete;
  const view = setup(() => new Promise(resolve => { complete = resolve; }));
  view.input.value = '2026-10-01';
  const pending = view.form.fire('submit');
  assert.equal(view.save.disabled, true);
  assert.equal(view.cancel.disabled, true);
  assert.equal(view.input.disabled, true);
  let prevented = false;
  view.dialog.fire('cancel', { preventDefault() { prevented = true; } });
  view.cancel.fire('click');
  await view.form.fire('submit');
  assert.equal(prevented, true);
  assert.equal(view.dialog.open, true);
  assert.equal(view.calls.length, 1);
  complete({ id: 'upload', document_date: '2026-10-01' });
  await pending;
  assert.equal(view.dialog.open, false);
  assert.equal(view.save.disabled, false);
});

test('cancel leaves the document unchanged and reopen resets stale errors', async () => {
  const view = setup();
  view.cancel.fire('click');
  assert.equal(view.dialog.open, false);
  assert.equal(view.calls.length, 0);
  view.status.textContent = 'previous error';
  view.editor.open({ id: 'another/id', title: 'Tài liệu khác', document_date: '' });
  assert.equal(view.input.value, '');
  assert.doesNotMatch(view.status.textContent, /previous error/);
  view.input.value = '2026-10-01';
  await view.form.fire('submit');
  assert.equal(view.calls[0][0], '/api/documents/another%2Fid/date');
});

test('a list refresh failure is not reported as an unsaved date', async () => {
  const view = setup(undefined, async () => { throw new Error('offline'); });
  view.input.value = '2026-10-01';
  await view.form.fire('submit');
  assert.equal(view.dialog.open, true);
  assert.match(view.status.textContent, /Ngày đã được lưu/);
  assert.match(view.status.textContent, /tải lại trang/);
  assert.equal(view.save.disabled, false);
});

test('document list exposes the editor only for uploads and refreshes metadata after save', async () => {
  const nodes = new Map();
  const node = key => {
    if (!nodes.has(key)) nodes.set(key, new Element());
    return nodes.get(key);
  };
  const button = new Element();
  button.dataset.editDate = 'upload';
  node('table').matches = { '[data-edit-date]': [button] };
  const uploaded = { id: 'upload', rid: 'UPL-A', kind: 'uploaded', title: 'Tài liệu', document_date: '2026-12-31' };
  const demo = { rid: 'DEMO', kind: 'demo', title: 'Minh họa' };
  let options, opened, requests = 0;
  const context = vm.createContext({
    document: {
      querySelector: selector => node(selector.match(/"([^"]+)"/)[1]),
      createElement: () => ({
        textContent: '',
        get innerHTML() { return this.textContent.replaceAll('&', '&amp;').replaceAll('<', '&lt;'); },
      }),
    },
    HocVuAPI: api,
    HocVuDocumentDates: {
      createDateEditor(value) { options = value; return { open(item) { opened = item; } }; },
    },
    fetch: async url => {
      assert.equal(url, '/api/documents');
      requests++;
      return { ok: true, json: async () => [uploaded, demo] };
    },
    confirm: () => true,
  });
  vm.runInContext(fs.readFileSync('ui/documents.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((node('table').innerHTML.match(/data-edit-date=/g) || []).length, 1);
  button.fire('click');
  assert.equal(opened.id, 'upload');
  uploaded.document_date = '2026-10-01';
  await options.onSaved(uploaded);
  assert.equal(requests, 2);
  assert.match(node('table').innerHTML, /2026-10-01/);
  assert.match(node('status').textContent, /Đã sửa ngày áp dụng/);
});

test('the page loads the editor script before the document controller and includes required dialog fields', () => {
  const html = fs.readFileSync('ui/documents.html', 'utf8');
  assert.ok(html.indexOf('src="document-date-editor.js') < html.indexOf('src="documents.js'));
  for (const name of ['date-dialog', 'date-form', 'date-input', 'date-name', 'date-status', 'date-cancel', 'date-save']) {
    assert.ok(html.includes(`data-doc="${name}"`), name);
  }
  assert.match(html, /data-doc="date-input" type="date" required/);
});
