'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

async function loadDocuments(onUpload = async () => {}, items = [], onRequest = async () => null) {
  const elements = new Map(), messages = [], uploads = [], requests = [];
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
      append(key, value) { this.fields.set(key, [...(this.fields.get(key) || []), value]); }
      get(key) { return this.fields.get(key)?.[0]; }
      getAll(key) { return this.fields.get(key) || []; }
    },
    confirm: () => true,
    HocVuAPI: require('../ui/api-errors.js'),
    HocVuDocumentDates: { createDateEditor() { return { open() {} }; } },
    fetch: async (url, options = {}) => {
      requests.push({ url, ...options });
      const response = await onRequest(url, options);
      if (response) return response;
      if (url === '/api/documents/upload-batch') {
        uploads.push(options.body);
        await onUpload(options.body, uploads.length);
        return { ok: true, json: async () => ({ items: options.body.getAll('files').map((_, i) => ({ id: String(i) })) }) };
      }
      if (url === '/api/documents/delete-batch') {
        return { ok: true, json: async () => ({ deleted: JSON.parse(options.body).ids, cleanup_pending: [] }) };
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
      globalThis.testDocs = { dom, addFiles, deleteDocuments, getQueue: () => queue,
        selectLibrary: (ids) => { librarySelection = new Set(ids); updateSelected(); },
        getSelection: () => [...librarySelection] };
    })();`);
  vm.runInNewContext(instrumented, sandbox, { filename });
  await sandbox.bootReady;
  const ui = sandbox.testDocs;
  return Object.assign(ui, {
    messages, uploads, requests,
    submit: () => ui.dom.form.events.submit({ preventDefault() {} }),
    progress: () => messages.filter(message => message.startsWith('Đang xử lý')),
  });
}
const file = name => ({ name, size: 128 });

test('three files and individual metadata go in one server transaction without extra reindex', async () => {
  const ui = await loadDocuments();
  ui.addFiles(['a.pdf', 'b.pdf', 'c.pdf'].map(file));
  Object.assign(ui.getQueue()[1], { ocr: true, order: '9', decision_number: '123/QĐ', article_clause: 'Điều 2', document_date: '2020-02-03' });
  await ui.submit();
  assert.equal(ui.uploads.length, 1);
  assert.deepEqual(Array.from(ui.uploads[0].getAll('files'), f => f.name), ['a.pdf', 'b.pdf', 'c.pdf']);
  assert.deepEqual(JSON.parse(ui.uploads[0].get('metadata'))[1], {
    ocr: true, order: '9', decision_number: '123/QĐ', article_clause: 'Điều 2', document_date: '2020-02-03',
  });
  assert.deepEqual(ui.progress(), ['Đang xử lý cả lô 3 tệp và lập chỉ mục một lần...']);
  assert.equal(ui.getQueue().length, 0);
  assert.equal(ui.dom.upload.disabled, true);
  assert.match(ui.dom.status.textContent, /3 tài liệu/);
  assert.equal(ui.requests.filter(r => r.method === 'POST').length, 1);
});

test('batch failure preserves every file and its metadata for retry', async () => {
  let fail = true;
  const ui = await loadDocuments(async () => {
    if (fail) throw Object.assign(new Error('Lỗi OCR; cả lô đã hoàn tác.'), { status: 400 });
  });
  ui.addFiles(['a.pdf', 'b.pdf', 'c.pdf'].map(file));
  ui.getQueue()[1].decision_number = 'ABC';
  await ui.submit();
  assert.match(ui.dom.status.textContent, /Lỗi OCR.*Hàng đợi được giữ lại/);
  assert.deepEqual(Array.from(ui.getQueue(), item => item.file.name), ['a.pdf', 'b.pdf', 'c.pdf']);
  assert.equal(ui.getQueue()[1].decision_number, 'ABC');
  assert.equal(ui.dom.upload.disabled, false);
  fail = false;
  await ui.submit();
  assert.equal(ui.uploads.length, 2);
  assert.equal(ui.uploads[1].getAll('files').length, 3);
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
  assert.deepEqual(ui.progress(), ['Đang xử lý cả lô 3 tệp và lập chỉ mục một lần...']);
  assert.deepEqual(Array.from(ui.getQueue(), item => item.file.name), ['next.pdf']);
  assert.equal(ui.dom.upload.disabled, false);
  await ui.submit();
  assert.equal(ui.progress().at(-1), 'Đang xử lý cả lô 1 tệp và lập chỉ mục một lần...');
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

test('lost upload response keeps the whole queue and warns that outcome is unknown', async () => {
  const ui = await loadDocuments(async () => { throw new TypeError('Mất mạng'); });
  ui.addFiles(['a.pdf', 'b.pdf'].map(file));
  await ui.submit();
  assert.equal(ui.getQueue().length, 2);
  assert.match(ui.dom.status.textContent, /máy chủ có thể đã hoàn tất/);
  assert.equal(ui.requests.filter(r => r.method === 'POST').length, 1);
  assert.equal(ui.dom.reindex.disabled, false);
});

test('a failed library refresh after upload does not undo or misreport a committed batch', async () => {
  let reads = 0;
  const ui = await loadDocuments(undefined, [], async url => {
    if (url === '/api/documents' && ++reads > 1) throw new TypeError('Mất mạng');
  });
  ui.addFiles([file('a.pdf')]);
  await ui.submit();
  assert.equal(ui.getQueue().length, 0);
  assert.match(ui.dom.status.textContent, /Đã tải lên.*Chưa tải lại được thư viện/);
  assert.equal(ui.dom.status.className, 'upload-status success');
});

test('queue enforces file count, per-file size and aggregate size limits', async () => {
  const ui = await loadDocuments();
  ui.addFiles(Array.from({ length: 21 }, (_, i) => file(`${i}.pdf`)));
  assert.equal(ui.getQueue().length, 20);
  assert.match(ui.dom.status.textContent, /20 tệp, tổng 50 MB/);
  const large = await loadDocuments();
  large.addFiles(['a.pdf', 'b.pdf', 'c.pdf'].map(name => ({ name, size: 25 * 1024 * 1024 })));
  assert.equal(large.getQueue().length, 2);
  const invalid = await loadDocuments();
  invalid.addFiles([{ name: 'empty.pdf', size: 0 }, { name: 'huge.pdf', size: 25 * 1024 * 1024 + 1 }]);
  assert.equal(invalid.getQueue().length, 0);
});

const library = ['a', 'b'].map(id => ({ id, rid: `UPL-${id}`, kind: 'uploaded', title: id }));
test('multiple deletions are one transaction with no browser finally reindex', async () => {
  const ui = await loadDocuments(undefined, library);
  ui.selectLibrary(['a', 'b']);
  await ui.deleteDocuments(['a', 'b']);
  const writes = ui.requests.filter(r => r.method === 'POST');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].url, '/api/documents/delete-batch');
  assert.deepEqual(JSON.parse(writes[0].body), { ids: ['a', 'b'] });
  assert.equal(ui.getSelection().length, 0);
  assert.match(ui.dom.status.textContent, /Đã xóa 2 tài liệu/);
});

test('failed deletion preserves every selected item and retry can succeed', async () => {
  let fail = true;
  const ui = await loadDocuments(undefined, library, async url => {
    if (url === '/api/documents/delete-batch' && fail) return { ok: false, status: 503, json: async () => ({ detail: 'Cả lô được giữ nguyên.' }) };
  });
  ui.selectLibrary(['a', 'b']);
  await ui.deleteDocuments(['a', 'b']);
  assert.deepEqual(Array.from(ui.getSelection()), ['a', 'b']);
  assert.match(ui.dom.status.textContent, /Cả lô được giữ nguyên/);
  assert.equal(ui.dom.removeLibrary.disabled, false);
  fail = false;
  await ui.deleteDocuments(['a', 'b']);
  assert.equal(ui.getSelection().length, 0);
});

test('lost deletion response does not claim success or clear the selection', async () => {
  const ui = await loadDocuments(undefined, library, async url => {
    if (url === '/api/documents/delete-batch') throw new TypeError('Mất mạng');
  });
  ui.selectLibrary(['a', 'b']);
  await ui.deleteDocuments(['a', 'b']);
  assert.deepEqual(Array.from(ui.getSelection()), ['a', 'b']);
  assert.match(ui.dom.status.textContent, /máy chủ có thể đã hoàn tất/);
  assert.equal(ui.dom.status.className, 'upload-status error');
});

test('too many selected documents cannot start a partial deletion', async () => {
  const ui = await loadDocuments();
  await ui.deleteDocuments(Array.from({ length: 21 }, (_, i) => String(i)));
  assert.equal(ui.requests.filter(r => r.method === 'POST').length, 0);
  assert.match(ui.dom.status.textContent, /tối đa 20 tài liệu/);
});

test('cleanup warning is not reported as a failed deletion', async () => {
  const ui = await loadDocuments(undefined, library, async url => {
    if (url === '/api/documents/delete-batch') return { ok: true, json: async () => ({ deleted: ['a', 'b'], cleanup_pending: ['a'] }) };
  });
  await ui.deleteDocuments(['a', 'b']);
  assert.match(ui.dom.status.textContent, /Đã xóa 2.*tệp gốc chưa dọn/);
  assert.equal(ui.dom.status.className, 'upload-status success');
});

test('all other mutation actions are blocked while a batch is active', async () => {
  let finish;
  const ui = await loadDocuments(async () => new Promise(resolve => { finish = resolve; }), library);
  ui.addFiles([file('a.pdf')]);
  const pending = ui.submit();
  // fetch enters an asynchronous hook first.
  while (!finish) await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.dom.reindex.disabled, true);
  await ui.deleteDocuments(['a', 'b']);
  await ui.dom.reindex.events.click();
  assert.equal(ui.requests.filter(r => r.method === 'POST').length, 1);
  finish();
  await pending;
});

test('administrator can create and download a private persistent backup', async () => {
  const ui = await loadDocuments(undefined, [], async url => {
    if (url === '/api/admin/storage/backup') return {
      ok: true, json: async () => ({
        filename: 'hocvu-20261020T000000Z-1234abcd.zip', persistent_copy: true,
      }),
    };
  });
  await ui.dom.backup.events.click();
  assert.equal(ui.requests.filter(r => r.url === '/api/admin/storage/backup').length, 1);
  assert.equal(ui.dom.backupDownload.hidden, false);
  assert.equal(ui.dom.backupDownload.href, '/api/admin/storage/backups/hocvu-20261020T000000Z-1234abcd.zip');
  assert.match(ui.dom.status.textContent, /App Storage/);
  assert.equal(ui.dom.backup.disabled, false);
});

test('local backup warns that downloading it is necessary', async () => {
  const ui = await loadDocuments(undefined, [], async url => {
    if (url === '/api/admin/storage/backup') return {
      ok: true, json: async () => ({ filename: 'hocvu-20261020T000000Z-1234abcd.zip', persistent_copy: false }),
    };
  });
  await ui.dom.backup.events.click();
  assert.match(ui.dom.status.textContent, /chưa được lưu bền vững/);
  assert.equal(ui.dom.status.className, 'upload-status warning');
});
