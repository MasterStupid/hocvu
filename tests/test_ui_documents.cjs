'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

async function loadDocuments(onUpload = async () => {}, items = []) {
  const elements = new Map(), messages = [], uploads = [];
  class Element {
    constructor(key) { this.key = key; this.events = {}; this.checked = false; this.classList = { add() {}, remove() {} }; }
    set textContent(value) { this.text = value; if (this.key === 'status') messages.push(value); }
    get textContent() { return this.text || ''; }
    get innerHTML() { return this.html ?? this.textContent.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
    set innerHTML(value) { this.html = value; }
    querySelectorAll() { return []; }
    addEventListener(name, callback) { this.events[name] = callback; }
  }
  const sandbox = {
    document: {
      querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, new Element(selector.match(/"([^"]+)"/)[1]));
        return elements.get(selector);
      },
      createElement() { return new Element(''); },
    },
    FormData: class {
      constructor() { this.fields = new Map(); }
      append(key, value) { this.fields.set(key, value); }
      get(key) { return this.fields.get(key); }
    },
    HocVuAPI: require('../ui/api-errors.js'),
    HocVuDocumentDates: { createDateEditor() { return { open() {} }; } },
    fetch: async (url, options = {}) => {
      if (url === '/api/documents/upload') {
        uploads.push(options.body);
        await onUpload(options.body, uploads.length);
        return { ok: true, json: async () => ({ id: String(uploads.length) }) };
      }
      return { ok: true, json: async () => items };
    },
  };
  const filename = path.join(__dirname, '..', 'ui', 'documents.js');
  const source = fs.readFileSync(filename, 'utf8');
  assert.ok(source.includes('renderQueue(); load().catch'));
  const instrumented = source
    .replace('renderQueue(); load().catch', 'renderQueue(); globalThis.bootReady = load().catch')
    .replace(/\}\)\(\);\s*$/, `
      globalThis.testDocs = { dom, addFiles, getQueue: () => queue };
    })();`);
  vm.runInNewContext(instrumented, sandbox, { filename });
  await sandbox.bootReady;
  const ui = sandbox.testDocs;
  return Object.assign(ui, {
    messages, uploads,
    submit: () => ui.dom.form.events.submit({ preventDefault() {} }),
    progress: () => messages.filter(message => message.startsWith('Đang xử lý')),
  });
}
const file = name => ({ name, size: 128 });

test('three files report 1/3, 2/3 and 3/3 even as the queue shrinks', async () => {
  const ui = await loadDocuments();
  ui.addFiles(['a.pdf', 'b.pdf', 'c.pdf'].map(file));
  await ui.submit();
  assert.deepEqual(ui.progress(), ['Đang xử lý 1/3: a.pdf', 'Đang xử lý 2/3: b.pdf', 'Đang xử lý 3/3: c.pdf']);
  assert.equal(ui.getQueue().length, 0);
  assert.equal(ui.dom.upload.disabled, true);
  assert.match(ui.dom.status.textContent, /3 tài liệu/);
});

test('failure preserves pending files and retry starts a new fixed-size batch', async () => {
  let fail = true;
  const ui = await loadDocuments(async (body, attempt) => {
    if (fail && attempt === 2) throw new Error('Lỗi OCR');
  });
  ui.addFiles(['a.pdf', 'b.pdf', 'c.pdf'].map(file));
  await ui.submit();
  assert.match(ui.dom.status.textContent, /1 tệp đã xong.*Lỗi OCR/);
  assert.deepEqual(Array.from(ui.getQueue(), item => item.file.name), ['b.pdf', 'c.pdf']);
  assert.equal(ui.dom.upload.disabled, false);
  fail = false;
  await ui.submit();
  assert.deepEqual(ui.progress().slice(-2), ['Đang xử lý 1/2: b.pdf', 'Đang xử lý 2/2: c.pdf']);
  assert.equal(ui.getQueue().length, 0);
});

test('an active batch cannot be submitted twice or changed by queued removals', async () => {
  let finishFirst;
  const ui = await loadDocuments(async (body, attempt) => {
    if (attempt === 1) await new Promise(resolve => { finishFirst = resolve; });
  });
  ui.addFiles(['a.pdf', 'b.pdf', 'c.pdf'].map(file));
  const pending = ui.submit();
  assert.equal(ui.dom.upload.disabled, true);
  await ui.submit();
  assert.equal(ui.uploads.length, 1);
  ui.getQueue()[1].selected = true;
  ui.dom.removeQueued.events.click();
  assert.equal(ui.getQueue().length, 3);
  ui.addFiles([file('next.pdf')]);
  assert.equal(ui.dom.upload.disabled, true);
  assert.equal(ui.dom.removeQueued.disabled, true);
  finishFirst();
  await pending;
  assert.deepEqual(ui.progress(), ['Đang xử lý 1/3: a.pdf', 'Đang xử lý 2/3: b.pdf', 'Đang xử lý 3/3: c.pdf']);
  assert.deepEqual(Array.from(ui.getQueue(), item => item.file.name), ['next.pdf']);
  assert.equal(ui.dom.upload.disabled, false);
  await ui.submit();
  assert.equal(ui.progress().at(-1), 'Đang xử lý 1/1: next.pdf');
});

test('empty queues never start a request', async () => {
  const ui = await loadDocuments();
  await ui.submit();
  assert.equal(ui.uploads.length, 0);
});

test('library preview, deletion and date edit buttons never submit a form', async () => {
  const ui = await loadDocuments(undefined, [{
    id: 'synthetic', rid: 'UPL-SYNTHETIC', kind: 'uploaded',
    title: 'Tài liệu', filename: 'document.pdf', format: 'PDF', status: 'ready',
  }]);
  const buttons = ui.dom.table.innerHTML.match(/<button\b[^>]*>/g) || [];
  assert.equal(buttons.length, 3);
  for (const attribute of ['data-edit-date', 'data-preview', 'data-delete']) {
    const button = buttons.find(tag => tag.includes(`${attribute}=`));
    assert.ok(button, `missing ${attribute}`);
    assert.match(button, /\btype="button"/);
  }
});
